"""Orchestration-agent node functions for the extraction workflow:
intake, cache check, model warmup, final merge, and finalize.

Graph wiring lives in extraction/workflows/extraction_workflow.py —
this module contains only node logic (the reference convention:
workflows wire, agents work).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agents.extraction.state import ExtractionState
from agents.retry import retryable_node
from agents.streaming import FatalAgentError, stage as emit_stage


def intake(state: ExtractionState) -> dict:
    source = Path(state["source_path"])
    if not source.exists():
        raise FatalAgentError(f"Source file not found: {source}")
    raw = source.read_bytes()
    fhash = hashlib.sha256(raw).hexdigest()
    suffix = source.suffix.lower()
    media_type = "application/pdf" if suffix == ".pdf" else "image/png"

    hub = Path(state["hub"])
    proj_dir = hub / "projects" / state["pid"]
    safe_name = re.sub(r"[^\w\-_. ]", "_", source.name).strip() or "source.pdf"
    (proj_dir / "source_docs").mkdir(parents=True, exist_ok=True)
    (proj_dir / "cache").mkdir(parents=True, exist_ok=True)
    (proj_dir / "source_docs" / safe_name).write_bytes(raw)

    if media_type == "application/pdf":
        emit_stage("pdf_render", "running")
        # lazy: needs pymupdf. render_pdf_pages_to_png handles N=1 (a
        # single-page PDF) identically to the old _render_pdf_to_png
        # single-page path — same per-page scaling rule, just returns a
        # one-element list instead of bare bytes.
        from extraction_cli.pdf import render_pdf_pages_to_png
        pages_bytes = render_pdf_pages_to_png(raw)
        page_paths: list[str] = []
        for i, png_bytes in enumerate(pages_bytes):
            page_path = proj_dir / "cache" / f"{state['pid']}_page_{i + 1}.png"
            page_path.write_bytes(png_bytes)
            page_paths.append(str(page_path))
        emit_stage("pdf_render", "complete", pages=len(page_paths),
                   bytes=sum(len(b) for b in pages_bytes))
    else:
        page_paths = [str(proj_dir / "source_docs" / safe_name)]

    emit_stage("init", "ok", hub=str(hub), pid=state["pid"],
               file=source.name, hash=fhash, pages=len(page_paths))
    return {
        "file_hash": fhash,
        "media_type": media_type,
        "page_paths": page_paths,
        "page_count": len(page_paths),
        "status": "running",
    }


def _agentic_cache_key(state: ExtractionState) -> str:
    return f"{state['file_hash']}_agentic_v1"


def cache_check(state: ExtractionState) -> dict:
    """Whole-file cache short-circuit. Tolerant: any failure means miss.

    CacheStore is DB-backed and keyed by (pid, key) — NOT by a
    filesystem path, despite accepting an hub-like constructor arg for
    historical API compatibility (see CacheStore.__init__'s docstring).
    Must call store.get(pid, key), not store.get(key).
    """
    try:
        from adapters.cache_store import CacheStore
        store = CacheStore(state["hub"])
        key = _agentic_cache_key(state)
        cached = store.get(state["pid"], key)
        if cached:
            emit_stage("cache", "hit", key=key)
            return {"cache_hit": True, "status": "cached",
                    "verified_nodes": cached.get("nodes", []),
                    "verified_edges": cached.get("edges", [])}
    except Exception:
        pass
    emit_stage("cache", "miss")
    return {"cache_hit": False}


def warmup(state: ExtractionState) -> dict:
    """Confirm the vision-LLM detectors are usable before any page runs.

    This node used to call bootstrap.cv_bootstrap._init_cv_models(), which
    loads YOLOv8, RapidOCR and U-Net — trained models, loaded on every agentic
    extraction run. That was the single largest piece of real ML involvement
    left in this pipeline, and it contradicted the design: detection here is
    pure LLM with no trained model anywhere in the loop.

    There is nothing to warm for a vision LLM, so the useful work at this stage
    is failing fast: check once, here, that the configured provider can
    actually accept an image, rather than discovering it tile by tile across
    every page.
    """
    from services.detection_router import (VisionUnavailable,
                                           provider_vision_status)
    has_vision, why = provider_vision_status()
    if not has_vision:
        # FatalAgentError, not a degraded pass: with no ML fallback there is
        # no way to continue, and a run that silently produced nothing would
        # look like a blank drawing rather than a misconfiguration.
        raise FatalAgentError(
            "Vision-capable model required — agentic detection is pure LLM "
            "and has no trained-model fallback. {}".format(why))
    emit_stage("warmup", "complete", engine="llm", vision=True, detail=why)
    return {}


def _on_merge_exhausted(state: ExtractionState, err: Exception) -> dict:
    """Degradation policy: surface the failure, keep the run resumable."""
    emit_stage("merge", "failed", detail=str(err)[:200])
    return {"verified_nodes": [], "verified_edges": [], "status": "degraded"}


def _collect_pages(state: ExtractionState) -> tuple[list[dict], list[dict]]:
    """Combine every page's namespaced nodes/edges into one flat pair.

    Two shapes are supported so single-page runs (the N=1 case — an
    image upload, or a one-page PDF that never entered the multi-page
    fan-out at all) behave EXACTLY as before this change:
      - page_pipeline_results present (multi-page fan-out ran): combine
        every page's already-namespaced {"nodes","edges"} in page order.
      - page_pipeline_results empty (no fan-out — legacy single-page
        path still populates llm_a_result/llm_b_result directly): fall
        back to the original single-page combination logic verbatim.
    """
    pages = state.get("page_pipeline_results") or {}
    if pages:
        nodes: list[dict] = []
        edges: list[dict] = []
        for key in sorted(pages, key=lambda k: int(k)):
            page = pages[key] or {}
            nodes.extend(page.get("nodes") or [])
            edges.extend(page.get("edges") or [])
        return nodes, edges

    llm_a = state.get("llm_a_result") or {}
    llm_b = state.get("llm_b_result") or {}
    nodes = list(llm_a.get("nodes") or [])
    edges = list(llm_b.get("edges") or [])
    known_ids = {n.get("id") for n in nodes}
    for j in llm_b.get("junctions") or []:
        jid = j.get("id")
        if jid and jid not in known_ids:
            nodes.append({"id": jid, "kind": "junction",
                          "x": j.get("x"), "y": j.get("y")})
            known_ids.add(jid)
    return nodes, edges


@retryable_node(max_attempts=2, label="merge_results",
                on_exhausted=_on_merge_exhausted)
def merge_results(state: ExtractionState) -> dict:
    """Combine every page's verified nodes + audited edges into the
    final graph, then persist through the classic writer for DB parity.
    See _collect_pages for the single-page/multi-page shape handling."""
    nodes, edges = _collect_pages(state)
    llm_a = state.get("llm_a_result") or {}

    # Backstop parity rule: edges touching isolated-flagged nodes drop.
    isolated = {n.get("id") for n in nodes if n.get("isolated_reason")}
    if isolated:
        edges = [e for e in edges
                 if e.get("from") not in isolated
                 and e.get("to") not in isolated]

    persisted = False
    try:
        import main as _s
        from extraction_cli.commands import _merge
        combined = {**llm_a, "nodes": nodes, "edges": edges}
        pages = state.get("page_pipeline_results") or {}
        combined["geometry"] = [v["geometry"] for _, v in sorted(
            pages.items(), key=lambda kv: int(kv[0])) if v.get("geometry")]
        _merge(state["pid"], combined,
               Path(state["source_path"]).name, state["file_hash"], _s,
               state.get("source_id"))
        persisted = True
    except Exception as e:
        emit_stage("merge", "not_persisted", detail=str(e)[:200])

    try:
        from adapters.cache_store import CacheStore
        CacheStore(state["hub"]).put(
            state["pid"], _agentic_cache_key(state),
            {"nodes": nodes, "edges": edges})
    except Exception:
        pass   # cache population is a nice-to-have, never fails the run

    emit_stage("merge", "complete", nodes=len(nodes), edges=len(edges),
               persisted=persisted)
    return {"verified_nodes": nodes, "verified_edges": edges}


def _usage_totals(state: ExtractionState) -> tuple[int, int, float]:
    records = state.get("usage") or []
    tin = sum(int(r.get("input_tokens", 0) or 0) for r in records)
    tout = sum(int(r.get("output_tokens", 0) or 0) for r in records)
    cost = round(sum(float(r.get("cost_usd", 0.0) or 0.0) for r in records), 6)
    return tin, tout, cost


def _node_category(n: dict) -> str:
    """category if _merge() already enriched the node; else derive it the
    same way _merge() does, so counts are correct even when the classic
    writer's DB persist step failed (merge_results keeps verified_nodes
    either way — see merge_results's try/except around _merge())."""
    if n.get("category"):
        return n["category"]
    from extraction_cli.commands import _KIND_TO_CATEGORY
    lookup = (n.get("type") or n.get("kind", "")).lower()
    return (_KIND_TO_CATEGORY.get(lookup)
            or _KIND_TO_CATEGORY.get(n.get("kind", ""), "mechanical"))


def finalize(state: ExtractionState) -> dict:
    status = state.get("status") or "running"
    if status == "running":
        status = "complete"
    tokens_in, tokens_out, cost_usd = _usage_totals(state)
    verified_nodes = state.get("verified_nodes") or []
    verified_edges = state.get("verified_edges") or []
    total_instruments = sum(1 for n in verified_nodes
                            if _node_category(n) == "instrument")
    total_equipment = sum(1 for n in verified_nodes
                          if _node_category(n) == "equipment")
    # "done" — the legacy extract_cli.py's terminal-success stage name.
    # Rust's extraction.rs (usage/cost persistence) and the frontend's
    # ExtractionContext.tsx (doneFired -> "extraction complete" UI state)
    # both hardcode a literal match on "done"; anything else here means
    # every successful agentic run gets misreported as a crash the
    # moment this pipeline is wired into the desktop app. See
    # agents/README.md's stage-naming note. tokens_in/tokens_out/cost_usd
    # are flat top-level fields (not nested) because extraction.rs reads
    # payload["tokens_in"] etc. directly off this same "done" line to
    # persist into cache_manifest for the UsageScreen. total_nodes/
    # total_instruments/total_equipment/total_connections are ADDITIVE
    # alongside nodes/edges (kept for the agentic test suite/anything
    # already depending on them) — extraction.rs's success gate reads
    # total_nodes, and the frontend's completion summary reads all four
    # total_* fields with no fallback for the latter three, so omitting
    # them would silently zero out the desktop app's summary line.
    emit_stage("done", status,
               nodes=len(verified_nodes),
               edges=len(verified_edges),
               proposals=len(state.get("proposals") or []),
               loops=len(state.get("loops") or []),
               qc_reports=len(state.get("qc_reports") or []),
               tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd,
               total_nodes=len(verified_nodes),
               total_instruments=total_instruments,
               total_equipment=total_equipment,
               total_connections=len(verified_edges))
    return {"status": status}


def configured_provider() -> str:
    """Active provider from the settings table; '' if unconfigured
    (controllers then run rules-only)."""
    try:
        from adapters.config import load_config
        return (load_config().get("llm_provider") or "").lower()
    except Exception:
        return ""

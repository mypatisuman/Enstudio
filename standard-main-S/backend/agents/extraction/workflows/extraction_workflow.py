"""Extraction workflow — graph assembly ONLY (the reference convention:
workflows wire, agents work).

Topology (single page path, kept 100% intact — see page_pipeline below
for how N pages reuse this exact chain unmodified):

  intake -> cache_check -> warmup -> [ per-page fan-out ]
  per page: symbol_detection -> [ text_detection ∥ line_detection ]
            text_detection -> llm_a   (early start: A never waits for lines)
            [ llm_a + line_detection ] -> cv_consolidation
            cv_consolidation -> relationship_building (or one-shot redispatch)
            relationship_building -> llm_b
  [ all pages joined ] -> merge_results -> inference_passes -> finalize

Multi-page design (E1): every agent from symbol_detection through llm_b
is UNCHANGED — none of symbol_agent.py / text_agent.py / line_agent.py /
cv_coordination.py / relationship_agent.py / harness_agent.py were
touched for this. Each of those agents already operates on flat,
single-page state keys (page_paths[0], symbol_detections, llm_a_result,
...) — exactly what one page's worth of processing needs. Instead of
rewriting every agent to be page-index-aware, the ENTIRE existing chain
is compiled once as page_pipeline (a real StateGraph, not a Python
loop), and _run_one_page invokes it once per page with
state["page_paths"] narrowed to that page's single path — so every
existing agent still sees "page_paths[0] is the page" exactly as
before. Results are namespaced with a "p{i}_" id prefix and collected
into page_pipeline_results before returning, so multiple pages can be
combined by merge_results without node-id collisions.

For a single-page run (one image upload, or a one-page PDF), the fan-out
degenerates to N=1 and produces byte-identical results to the pre-E1
pipeline — see tests/test_extraction_multipage.py's regression case.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from agents.extraction.state import ExtractionState
from agents.streaming import FatalAgentError, emit, stage as emit_stage
from agents.extraction.agents import orchestration as O
from agents.extraction.agents.symbol_agent import build_symbol_agent
from agents.extraction.agents.text_agent import build_text_agent
from agents.extraction.agents.line_agent import build_line_agent
from agents.extraction.agents.cv_coordination import consolidate_node
from agents.extraction.agents.relationship_agent import build_relationship_agent
from agents.extraction.agents.harness_agent import llm_a_node, llm_b_node
from agents.extraction.agents.inference_agent import inference_node


# ── Subgraph wrapping ────────────────────────────────────────────────────────
# A compiled subgraph used directly as a node returns its ENTIRE final
# state, which collides on single-value channels when branches run in
# parallel. Each specialist is therefore wrapped to return only the keys
# it owns, plus the *delta* of accumulator channels (qc_reports, usage).

def _wrap_subgraph(agent, own_keys: tuple[str, ...]):
    def node(state: ExtractionState) -> dict:
        result = agent.invoke(state)
        out = {k: result[k] for k in own_keys if k in result}
        for acc in ("qc_reports", "usage"):
            base = len(state.get(acc) or [])
            delta = (result.get(acc) or [])[base:]
            if delta:
                out[acc] = delta
        for merged in ("retry_counts", "retry_params"):
            if result.get(merged):
                out[merged] = result[merged]   # merge-reducer channel: safe
        return out
    return node


def _route_after_consolidation(state: ExtractionState) -> str:
    reports = [r for r in (state.get("qc_reports") or [])
               if r.get("stage") == "cv_consolidation"]
    if reports and reports[-1].get("action_taken") == "redispatch":
        return "redispatch"
    return "proceed"


def build_page_pipeline():
    """The classic single-page chain, compiled as its own graph so it
    can be invoked once per page. Identical topology to what used to be
    wired directly into the top-level workflow — no node was added,
    removed, or reordered relative to the pre-E1 version."""
    g = StateGraph(ExtractionState)

    g.add_node("symbol_detection",
               _wrap_subgraph(build_symbol_agent(),
                              ("symbol_detections", "image_size")))
    g.add_node("text_detection",
               _wrap_subgraph(build_text_agent(),
                              ("text_detections", "text_escalations")))
    g.add_node("line_detection",
               _wrap_subgraph(build_line_agent(), ("line_segments",)))
    g.add_node("llm_a", lambda state: llm_a_node(state))
    g.add_node("cv_consolidation", consolidate_node)
    g.add_node("relationship_building",
               _wrap_subgraph(build_relationship_agent(),
                              ("candidate_graph",)))
    g.add_node("llm_b", lambda state: llm_b_node(state))

    g.add_edge(START, "symbol_detection")
    g.add_edge("symbol_detection", "text_detection")
    g.add_edge("symbol_detection", "line_detection")
    g.add_edge("text_detection", "llm_a")
    g.add_edge(["llm_a", "line_detection"], "cv_consolidation")
    g.add_conditional_edges("cv_consolidation", _route_after_consolidation,
                            {"proceed": "relationship_building",
                             "redispatch": "symbol_detection"})
    g.add_edge("relationship_building", "llm_b")
    g.add_edge("llm_b", END)

    return g.compile()


def _page_pipeline():
    # Rebuilt per call rather than cached: llm_a_node/llm_b_node are
    # referenced by module-attribute lookup inside the lambdas above, so
    # a monkeypatch on the *module* still redirects correctly either
    # way — but not caching avoids any other form of cross-test/cross-run
    # state leakage from a long-lived compiled graph object, and
    # StateGraph.compile() is cheap (no I/O, no model loading).
    return build_page_pipeline()


def _namespace_page_results(page_index: int, llm_a: dict, llm_b: dict,
                            source_id: int | None = None,
                            total_pages: int = 1,
                            image_size: dict | None = None,
                            candidate_graph: dict | None = None,
                            symbols: list | None = None,
                            annotations: dict | None = None) -> dict:
    """Scope one page's ids and stamp its document/page identity.

    PARITY NOTE. This used to apply its own "p{index}_" prefix (0-based) and
    stamp nothing else, which diverged from the classic pipeline in three ways
    that mattered once the desktop app could actually run this engine:

      * ids  — classic uses _id_prefix(source_id, page_no, total_pages), i.e.
               "s{src}_p{page}_", 1-based, and EMPTY for a single-page document
               with no source_id. Two documents extracted into one project both
               produced "p0_n1" under the old scheme, and the nodes table is
               keyed (id, pid), so the second extraction silently replaced the
               first document's rows.
      * source_id — never stamped, so nodes could not be attributed to the
               document they came from and _merge could not tell this run's
               rows from another document's.
      * page / page_w / page_h / drawing — never stamped, so the canvas had no
               sheet grouping and fell back to one fixed cell size per drawing.

    All four now follow the classic helpers directly (imported, not
    reimplemented) so the two engines produce interchangeable output.
    """
    from extraction_cli.commands import (_fallback_drawing, _id_prefix,
                                         _scope_ids)

    page_no = page_index + 1

    nodes = [dict(n) for n in (llm_a.get("nodes") or [])]
    known_ids = {n.get("id") for n in nodes}
    for j in (llm_b.get("junctions") or []):
        jid = j.get("id")
        if jid and jid not in known_ids:
            nodes.append({"id": jid, "kind": "junction",
                          "x": j.get("x"), "y": j.get("y")})
            known_ids.add(jid)

    edges = [dict(e) for e in (llm_b.get("edges") or [])]

    # Drop edges touching a node LLM A flagged as isolated. Done BEFORE
    # scoping so the comparison is against unprefixed ids, exactly as the
    # pre-parity version did.
    isolated = {n.get("id") for n in nodes if n.get("isolated_reason")}
    if isolated:
        edges = [e for e in edges
                 if e.get("from") not in isolated and e.get("to") not in isolated]

    prefix = _id_prefix(source_id, page_no, total_pages)

    # Tie each audited edge to the detected pipe run that backs it, the same
    # way the classic pipeline does, so geometry can be persisted and exported.
    geometry = None
    if candidate_graph is not None:
        from services.geometry_store import (link_edges_to_lines, page_geometry,
                                             scope_page, stamp_symbol_bboxes)
        by_pair = {frozenset((e.get("from"), e.get("to"))): e.get("line_indices")
                   for e in (candidate_graph.get("edges") or []) if e.get("line_indices")}
        for e in edges:
            idx = by_pair.get(frozenset((e.get("from"), e.get("to"))))
            if idx:
                e["line_indices"] = list(idx)
        size = image_size or {}
        raw = page_geometry(candidate_graph, symbols, size.get("width") or 0,
                            size.get("height") or 0, annotations)
        stamp_symbol_bboxes(nodes, raw)
        link_edges_to_lines(edges, prefix)
        geometry = {"page": page_no, **scope_page(raw, prefix)}

    _scope_ids(prefix, nodes, edges)

    drawing = (llm_a.get("drawing") or {}).get("number") if isinstance(
        llm_a.get("drawing"), dict) else llm_a.get("drawing")
    drawing = drawing or _fallback_drawing(source_id, page_no, total_pages)

    size = image_size or {}
    page_w, page_h = size.get("width"), size.get("height")
    for n in nodes:
        n["page"] = page_no
        if source_id is not None:
            n["source_id"] = int(source_id)
        if page_w and page_h:
            n["page_w"] = page_w
            n["page_h"] = page_h
        if drawing and not n.get("drawing"):
            n["drawing"] = drawing

    out = {"nodes": nodes, "edges": edges}
    if geometry is not None:
        out["geometry"] = geometry
    return out


def _run_one_page(state: ExtractionState) -> dict:
    """Send target: invoke the unmodified page_pipeline against exactly
    one page's path, then namespace and collect its result. Runs with
    the full ExtractionState so every existing agent's assumptions
    (page_paths[0], state["pid"], state["hub"], ...) hold — only
    page_paths is narrowed to this page."""
    page_index = state["page_index"]
    page_path = state["page_paths"][page_index]
    per_page_state = {**state, "page_paths": [page_path]}
    emit_stage("page_pipeline", "running", page=page_index + 1,
               of=state.get("page_count", 1))

    result = _page_pipeline().invoke(per_page_state)

    annotations, annotation_usage = _flow_annotations(page_path, result)

    combined = _namespace_page_results(
        page_index, result.get("llm_a_result") or {},
        result.get("llm_b_result") or {},
        source_id=state.get("source_id"),
        total_pages=state.get("page_count", 1),
        image_size=result.get("image_size") or {},
        candidate_graph=result.get("candidate_graph"),
        symbols=result.get("symbol_detections"),
        annotations=annotations)
    emit_stage("page_pipeline", "complete", page=page_index + 1,
               nodes=len(combined["nodes"]), edges=len(combined["edges"]))

    out: dict = {"page_pipeline_results": {str(page_index): combined}}
    for acc in ("qc_reports", "usage"):
        delta = result.get(acc) or []
        if delta:
            out[acc] = delta
    if annotation_usage:
        out["usage"] = list(out.get("usage") or []) + annotation_usage
    return out


def _flow_annotations(page_path: str, result: dict) -> tuple[dict | None, list]:
    """Flow arrows and heat tracing for one page, the same separate pass the
    classic pipeline runs (services/llm_flow_annotation_service.py). Only when
    the page produced geometry to attach them to. Never fails the page."""
    from services.llm_flow_annotation_service import detect_flow_annotations, enabled
    if not enabled() or result.get("candidate_graph") is None:
        return None, []
    try:
        from agents.extraction.agents.harness_agent import _usage_record
        from services.llm_symbol_detection_service import _studio_module
        found = detect_flow_annotations(_studio_module(), Path(page_path).read_bytes())
    except Exception as exc:
        emit_stage("flow_annotations", "failed", error=str(exc)[:200])
        return None, []
    emit_stage("flow_annotations", "complete", arrows=len(found["arrows"]),
               heat_trace_segments=len(found["heat_trace"]), failed_crops=found["failed"])
    return found, [_usage_record("flow_annotations", r) for r in found["usage"]]


def _fan_out_pages(state: ExtractionState):
    """Send one _run_one_page invocation per page. N=1 (a single image,
    or a one-page PDF) sends exactly once — the degenerate case that
    must behave identically to the pre-E1 single-page pipeline."""
    n = len(state.get("page_paths") or [])
    return [Send("page_pipeline", {**state, "page_index": i})
            for i in range(n)]


def _route_after_cache(state: ExtractionState) -> str:
    return "finalize" if state.get("cache_hit") else "warmup"


def build_extraction_workflow(checkpointer=None):
    g = StateGraph(ExtractionState)

    g.add_node("intake", O.intake)
    g.add_node("cache_check", O.cache_check)
    g.add_node("warmup", O.warmup)
    g.add_node("page_pipeline", _run_one_page)
    g.add_node("merge_results", O.merge_results)
    g.add_node("inference_passes", inference_node)
    g.add_node("finalize", O.finalize)

    g.add_edge(START, "intake")
    g.add_edge("intake", "cache_check")
    g.add_conditional_edges("cache_check", _route_after_cache,
                            {"warmup": "warmup", "finalize": "finalize"})
    g.add_conditional_edges("warmup", _fan_out_pages, ["page_pipeline"])
    g.add_edge("page_pipeline", "merge_results")
    g.add_edge("merge_results", "inference_passes")
    g.add_edge("inference_passes", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)


# Back-compat alias (pre-restructure name).
build_supervisor = build_extraction_workflow


def run_extraction_agentic(hub: str, pid: str, source_path: str,
                           *, llm_only: bool = False,
                           source_id: int | None = None,
                           use_checkpointer: bool = True) -> dict:
    """Programmatic entry point. Returns the final state dict."""
    from agents.checkpoints import make_checkpointer, thread_id

    checkpointer = make_checkpointer(hub) if use_checkpointer else None
    graph = build_extraction_workflow(checkpointer)

    initial: ExtractionState = {
        "pid": pid, "hub": hub, "source_path": source_path,
        "llm_only": llm_only, "provider": O.configured_provider(),
        "source_id": source_id,
        "retry_counts": {}, "retry_params": {},
    }
    config = {}
    if checkpointer is not None:
        raw = Path(source_path).read_bytes()
        fhash = hashlib.sha256(raw).hexdigest()
        config = {"configurable": {"thread_id": thread_id(pid, fhash)}}

    try:
        final = graph.invoke(initial, config or None)
    except FatalAgentError as e:
        # "error" (not "done"/"finish") — matches the legacy CLI's
        # terminal-failure stage name, which Rust's extraction.rs and the
        # frontend's ExtractionContext.tsx both key off of to set
        # errorFired. Using the success-terminal name here would make a
        # crashed run look completed on both the usage-tracking and UI
        # sides.
        emit({"stage": "error", "status": "failed", "message": str(e)})
        return {**initial, "status": "failed", "error": str(e)}
    return final

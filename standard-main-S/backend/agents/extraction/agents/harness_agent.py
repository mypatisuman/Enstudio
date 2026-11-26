"""Harness Agent — the two-LLM verification unit.

Exposes two supervisor nodes rather than one subgraph, because the two
halves run at different times by design:

  llm_a_node  — Symbol Verifier. Depends only on [symbol, text] outputs,
                so it runs while the Line agent is still working (the
                classic pipeline's early-start, expressed structurally).
  llm_b_node  — Connection Auditor. Depends on the candidate graph.

Both reuse the proven vision prompts via extraction_cli/llm_verification
(CV_VERIFY_PROMPT / CV_CONNECTIONS_PROMPT) and the json_utils armor that
those functions already apply internally. New here: the unreadable-crops
addendum for A, and the deletion-justification escalation after B.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from agents.extraction.state import ExtractionState
from agents.retry import retryable_node
from agents.streaming import stage as emit_stage
from agents.toolkit import parse_controller_json, qc_report
from agents.prompts import fill_prompt
from agents.extraction.prompts.catalog import (DELETION_JUSTIFY_V1,
                                        UNREADABLE_CROPS_ADDENDUM_V1)

STAGE_A = "llm_verification_a"
STAGE_B = "llm_verification_b"
DELETION_ESCALATION_THRESHOLD = 0.30


def _studio_module():
    import main as _s
    return _s


def _page_bytes(state: ExtractionState) -> bytes:
    return Path(state["page_paths"][0]).read_bytes()


def _usage_record(stage: str, resp) -> dict:
    """Build an ExtractionState UsageRecord from an LLMResponse (or dict-
    shaped equivalent) — same dual handling as CacheStore._scan_record,
    since providers can return either shape."""
    if isinstance(resp, dict):
        tin = int(resp.get("tokens_in", 0) or 0)
        tout = int(resp.get("tokens_out", 0) or 0)
        model = resp.get("model", "")
        provider = resp.get("provider", "")
        cost = float(resp.get("cost_usd", 0.0) or 0.0)
    else:
        tin = int(getattr(resp, "input_tokens", 0) or 0)
        tout = int(getattr(resp, "output_tokens", 0) or 0)
        model = getattr(resp, "model", "")
        provider = getattr(resp, "provider", "")
        cost = float(getattr(resp, "cost_usd", 0.0) or 0.0)
    return {"stage": stage, "provider": provider, "model": model,
            "input_tokens": tin, "output_tokens": tout, "cost_usd": cost}


def _conventions_text(state: ExtractionState) -> str:
    """Company conventions/skill text for this project, or '' if the
    project has no company set or no conventions file exists. Same
    resolution as the classic pipeline's extraction_controller.py
    (_get_conventions(pid).as_skill_text()) — kept independent here
    rather than imported, since the classic version reads main.py's
    Flask-request-scoped HUB/PROJECTS_DIR globals.
    """
    try:
        from services.convention_service import _get_conventions
        conv = _get_conventions(state["pid"], Path(state["hub"]),
                                Path(state["hub"]) / "projects")
        return conv.as_skill_text() if conv else ""
    except Exception:
        return ""


def _on_llm_a_exhausted(state: ExtractionState, err: Exception) -> dict:
    """Degradation policy: run continues without verified symbols."""
    emit_stage(STAGE_A, "failed", detail=str(err)[:200])
    return {
        "llm_a_result": {"nodes": [], "error": str(err)[:200]},
        "status": "degraded",
        "qc_reports": [qc_report(STAGE_A, "failed", {}, "degrade",
                                 f"LLM A failed: {err}", "rules")],
    }


@retryable_node(max_attempts=2, label=STAGE_A,
                on_exhausted=_on_llm_a_exhausted)
def llm_a_node(state: ExtractionState) -> dict:
    """LLM A — verify/correct/merge symbols; optionally read escalated tags."""
    from extraction_cli.llm_verification import (_build_symbol_summary,
                                                 _call_llm_verification)
    symbols = state.get("symbol_detections") or []
    texts = state.get("text_detections") or []
    size = state.get("image_size") or {}
    img_w, img_h = size.get("width", 1) or 1, size.get("height", 1) or 1

    summary = _build_symbol_summary(symbols, texts, img_w, img_h)
    escalations = state.get("text_escalations") or []
    if escalations:
        summary += fill_prompt(UNREADABLE_CROPS_ADDENDUM_V1,
                               {"crop_list": escalations})

    emit_stage(STAGE_A, "running", symbols=len(symbols),
               escalated_crops=len(escalations))
    result, resp = _call_llm_verification(
        _studio_module(), _page_bytes(state), "image/png",
        summary, img_w, img_h, raw_lines=[],
        conventions_text=_conventions_text(state))
    from agents.extraction.schemas import LLMAResult
    result = {**result, **LLMAResult.ensure_compliant(result)}
    nodes = result.get("nodes", [])
    emit_stage(STAGE_A, "complete", nodes=len(nodes))
    return {
        "llm_a_result": result,
        "usage": [_usage_record(STAGE_A, resp)],
        "qc_reports": [qc_report(STAGE_A, "ok", {"nodes": len(nodes)},
                                 "proceed", "symbol verification done",
                                 "rules")],
    }


def _on_llm_b_exhausted(state: ExtractionState, err: Exception) -> dict:
    """Degradation policy: keep the geometric candidate graph unaudited —
    uncertainty still reaches the Review screen; never lose edges."""
    geo = state.get("candidate_graph") or {}
    emit_stage(STAGE_B, "failed", detail=str(err)[:200])
    return {
        "llm_b_result": {"edges": geo.get("edges", []),
                         "junctions": geo.get("junctions", []),
                         "unaudited": True},
        "qc_reports": [qc_report(STAGE_B, "failed", {}, "degrade",
                                 f"LLM B failed: {err}; kept candidate "
                                 "graph unaudited", "rules")],
    }


@retryable_node(max_attempts=2, label=STAGE_B,
                on_exhausted=_on_llm_b_exhausted)
def llm_b_node(state: ExtractionState) -> dict:
    """LLM B — audit the candidate graph's connections."""
    from extraction_cli.llm_verification import (_build_symbol_summary,
                                                 _call_llm_connections,
                                                 _format_proposed_graph)
    geo = state.get("candidate_graph") or {}
    llm_a_nodes = (state.get("llm_a_result") or {}).get("nodes") or []
    proposed = geo.get("edges", [])
    size = state.get("image_size") or {}
    img_w, img_h = size.get("width", 1) or 1, size.get("height", 1) or 1

    if not llm_a_nodes:
        emit_stage(STAGE_B, "skipped", reason="no verified nodes (degraded)")
        return {"llm_b_result": {"edges": [], "junctions": []}}

    graph_text = _format_proposed_graph(geo, llm_a_nodes)
    if geo.get("sparse_flag"):
        graph_text += ("\nNOTE: geometric line coverage on this page is "
                       "sparse — lean on the image itself for connectivity.")
    conn_summary = _build_symbol_summary(
        state.get("symbol_detections") or [],
        state.get("text_detections") or [], img_w, img_h)

    emit_stage(STAGE_B, "running", proposed_edges=len(proposed))
    result, resp = _call_llm_connections(
        _studio_module(), _page_bytes(state), "image/png",
        conn_summary, proposed_graph_text=graph_text,
        conventions_text=_conventions_text(state))
    from agents.extraction.schemas import LLMBResult
    result = {**result, **LLMBResult.ensure_compliant(result)}

    kept = result.get("edges", [])
    deleted_frac = (1 - len(kept) / len(proposed)) if proposed else 0.0
    emit_stage(STAGE_B, "complete", kept=len(kept),
               deleted_fraction=round(deleted_frac, 3))

    if proposed and deleted_frac > DELETION_ESCALATION_THRESHOLD:
        result = _escalate_deletions(state, result, proposed)

    return {
        "llm_b_result": result,
        "usage": [_usage_record(STAGE_B, resp)],
        "qc_reports": [qc_report(
            STAGE_B, "ok" if deleted_frac <= DELETION_ESCALATION_THRESHOLD
            else "suspect",
            {"proposed": len(proposed), "kept": len(result.get("edges", [])),
             "deleted_fraction": round(deleted_frac, 3)},
            "proceed", "connection audit done", "rules")],
    }


def _escalate_deletions(state: ExtractionState, result: dict,
                        proposed: list) -> dict:
    """Second B pass: every deletion must be justified or it is restored."""
    kept_keys = {(e.get("from"), e.get("to")) for e in result.get("edges", [])}
    deleted = [e for e in proposed
               if (e.get("from"), e.get("to")) not in kept_keys]
    emit_stage(STAGE_B, "escalating", deletions=len(deleted))
    try:
        from adapters.llm_factory import get_provider
        provider = get_provider()
        prompt = fill_prompt(DELETION_JUSTIFY_V1, {
            "n_deleted": len(deleted), "n_total": len(proposed),
            "deleted_edges_with_context": json.dumps(deleted)[:8000]})
        img_b64 = base64.b64encode(_page_bytes(state)).decode()
        resp = provider.complete_with_image(prompt, img_b64, "image/png",
                                            tier="smart")
        decisions = (parse_controller_json(resp.text) or {}).get("decisions", [])
        restore_keys = {
            tuple(d.get("edge", "").split("->", 1))
            for d in decisions if d.get("action") == "restore"}
        restored = [e for e in deleted
                    if (str(e.get("from")), str(e.get("to"))) in restore_keys
                    or f"{e.get('from')}->{e.get('to')}" in
                    {d.get("edge") for d in decisions
                     if d.get("action") == "restore"}]
        if restored:
            emit_stage(STAGE_B, "restored", edges=len(restored))
            return {**result, "edges": result.get("edges", []) + restored}
    except Exception as e:
        emit_stage(STAGE_B, "escalation_failed", detail=str(e)[:200])
    return result

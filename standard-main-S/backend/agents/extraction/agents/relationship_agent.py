"""Relationship Building Agent — deterministic geometric candidate graph.

Subgraph: build -> qc -> (retry build | done)
Tool core: connectivity_graph.build_geometric_connectivity. Geometry is
never LLM-touched; the controller may widen the endpoint-cluster
tolerance once, or flag the page as genuinely sparse for the audit stage.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from agents.extraction.state import ExtractionState, can_retry, retries_used
from agents.streaming import stage as emit_stage
from agents.toolkit import qc_report, run_controller
from agents.extraction.prompts.catalog import GEOMETRY_QC_V1

STAGE = "relationship_building"
DEFAULT_PARAMS = {"cluster_tol": None}      # None = module default (18px)
ALLOWED_ACTIONS = {"proceed", "retry_wider_cluster", "proceed_flag_sparse"}


def _call_geometry(symbols: list, lines: list,
                   cluster_tol: int | None) -> dict:
    import connectivity_graph as cg
    saved = None
    try:
        if cluster_tol is not None:
            saved = cg.ENDPOINT_CLUSTER_TOL_PX
            cg.ENDPOINT_CLUSTER_TOL_PX = cluster_tol
        return cg.build_geometric_connectivity(symbols, lines)
    finally:
        if saved is not None:
            cg.ENDPOINT_CLUSTER_TOL_PX = saved


def _rule_fallback(metrics: dict) -> dict:
    if metrics["retries_used"] >= 2:
        return {"verdict": "ok", "action": "proceed",
                "reason": "retry budget exhausted; proceeding"}
    if metrics["edge_node_ratio"] < 0.30 and metrics["open_stubs"] > 5:
        if metrics["stubs_with_candidates"] >= metrics["open_stubs"] * 0.6:
            return {"verdict": "suspect", "action": "retry_wider_cluster",
                    "reason": "near-miss stubs dominate; widening cluster"}
        return {"verdict": "suspect", "action": "proceed_flag_sparse",
                "reason": "stubs lack candidates; lines absent, audit on image"}
    return {"verdict": "ok", "action": "proceed", "reason": "graph nominal"}


def build_node(state: ExtractionState) -> dict:
    params = {**DEFAULT_PARAMS,
              **(state.get("retry_params") or {}).get(STAGE, {})}
    # Classic pipeline order: geometry runs against LLM A's verified node
    # list when available (added symbols get synthetic bboxes upstream);
    # falls back to raw CV detections.
    symbols = ((state.get("llm_a_result") or {}).get("nodes")
               or state.get("symbol_detections") or [])
    symbols = [s for s in symbols if s.get("bbox")]
    lines = (state.get("line_segments") or {}).get("consolidated") or []

    emit_stage(STAGE, "running", symbols=len(symbols), segments=len(lines),
               attempt=retries_used(state, STAGE) + 1)
    try:
        geo = _call_geometry(symbols, lines, params["cluster_tol"])
    except Exception as e:
        emit_stage(STAGE, "failed", detail=str(e)[:200])
        geo = {"edges": [], "junctions": [], "open_stubs": [],
               "ambiguous_crossings": [], "unmatched_symbols": [],
               "lines": lines, "error": str(e)[:200]}
    emit_stage(STAGE, "complete", edges=len(geo.get("edges", [])),
               stubs=len(geo.get("open_stubs", [])))
    return {"candidate_graph": geo}


def qc_node(state: ExtractionState) -> dict:
    geo = state.get("candidate_graph") or {}
    symbols = ((state.get("llm_a_result") or {}).get("nodes")
               or state.get("symbol_detections") or [])
    used = retries_used(state, STAGE)
    stubs = geo.get("open_stubs", [])
    params = {**DEFAULT_PARAMS,
              **(state.get("retry_params") or {}).get(STAGE, {})}

    metrics = {
        "edges": len(geo.get("edges", [])),
        "edge_node_ratio": round(len(geo.get("edges", [])) / len(symbols), 3)
        if symbols else 0.0,
        "open_stubs": len(stubs),
        "stubs_with_candidates": sum(1 for s in stubs
                                     if s.get("candidate_symbol")),
        "ambiguous_crossings": len(geo.get("ambiguous_crossings", [])),
        "unmatched_symbols": len(geo.get("unmatched_symbols", [])),
        "tolerances_used": {"cluster_px": params["cluster_tol"] or 18},
        "retries_used": used,
    }

    decision, controller, usage = run_controller(
        GEOMETRY_QC_V1, metrics, _rule_fallback,
        allowed_actions=ALLOWED_ACTIONS, stage=STAGE,
        use_llm=bool(state.get("provider")))

    action = decision["action"]
    reason = decision.get("reason", "")
    if action == "retry_wider_cluster" and not can_retry(state, STAGE):
        reason = f"{reason} (retry budget exhausted; forced proceed)".strip()
        action = "proceed"

    updates: dict = {
        "qc_reports": [qc_report(STAGE, decision.get("verdict", "ok"),
                                 metrics, action, reason, controller)],
    }
    if usage:
        updates["usage"] = [usage]

    if action == "retry_wider_cluster":
        updates["retry_counts"] = {STAGE: used + 1}
        updates["retry_params"] = {STAGE: {"cluster_tol": 24}}
        emit_stage(STAGE, "retrying", action=action, reason=reason)
    elif action == "proceed_flag_sparse":
        updates["candidate_graph"] = {**geo, "sparse_flag": True}
    return updates


def _route_after_qc(state: ExtractionState) -> str:
    last = (state.get("qc_reports") or [{}])[-1]
    if last.get("stage") == STAGE and \
            last.get("action_taken") == "retry_wider_cluster":
        return "build"
    return END


def build_relationship_agent():
    g = StateGraph(ExtractionState)
    g.add_node("build", build_node)
    g.add_node("qc", qc_node)
    g.add_edge(START, "build")
    g.add_edge("build", "qc")
    g.add_conditional_edges("qc", _route_after_qc, {"build": "build", END: END})
    return g.compile()

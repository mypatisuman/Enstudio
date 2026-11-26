"""Line Detection Agent — vision-LLM pipe/signal line tracing.

Subgraph: detect -> qc -> (retry detect | done)
Tool core: services/llm_line_detection_service.py — no U-Net, no Hough
transform; every trace is a vision-LLM call, followed by a full-page
verification pass (see that module's docstring for the two-pass design).

Non-retry refinement actions (drop_leaders, unfuse_parallels,
classify_styles) are applied in-place during QC — they are cheap
post-processing over the already-detected segments, reused UNCHANGED from
services/line_detection_service.py regardless of which detector produced
the segments. classify_styles is largely redundant now (the tracing prompt
already tags solid/dashed per run) but stays available as a CV cross-check.
"""
from __future__ import annotations

import math
from pathlib import Path

from langgraph.graph import StateGraph, START, END

from agents.extraction.state import ExtractionState, can_retry, retries_used
from agents.streaming import stage as emit_stage
from agents.toolkit import qc_report, run_controller
from agents.extraction.prompts.catalog import LINE_QC_V1

STAGE = "line_detection"
DEFAULT_PARAMS = {"reprompt": False}
ALLOWED_ACTIONS = {"proceed", "retry_reprompt", "unfuse_parallels",
                   "drop_leaders", "classify_styles"}
HEALTHY_SEG_PER_SYMBOL = (1.5, 6.0)


def _call_lines(image_bytes: bytes, symbol_boxes: list, base_name: str,
                output_dir: str | None, reprompt: bool) -> dict:
    from services.detection_router import resolve_backend
    detect_lines_from_bytes = resolve_backend().detect_lines
    return detect_lines_from_bytes(
        image_bytes, symbol_boxes=symbol_boxes,
        output_dir=output_dir, base_name=base_name, reprompt=reprompt)


def _seg_len(seg: list) -> float:
    return math.hypot(seg[2] - seg[0], seg[3] - seg[1])


def _gray_page(page_path: str):
    try:
        import cv2
        import numpy as np
        arr = cv2.imdecode(
            np.frombuffer(Path(page_path).read_bytes(), np.uint8),
            cv2.IMREAD_GRAYSCALE)
        return arr
    except Exception:
        return None


def classify_styles(lines: dict, page_path: str) -> dict:
    """Activate the dormant dashed/solid classifier: dashed long lines
    move to signal_lines. No-op (returns input) when cv2 is unavailable."""
    gray = _gray_page(page_path)
    if gray is None:
        return lines
    from services.geometry.line_geometry import _classify_line_style
    solid, dashed = [], []
    for seg in lines.get("long_lines", []):
        (dashed if _classify_line_style(gray, seg) == "dashed"
         else solid).append(seg)
    return {**lines, "long_lines": solid,
            "signal_lines": lines.get("signal_lines", []) + dashed}


def drop_leaders(lines: dict, symbol_boxes: list) -> dict:
    try:
        from services.geometry.line_geometry import _filter_leader_lines
        boxes = [tuple(s["bbox"]) for s in symbol_boxes]
        return {**lines,
                "long_lines": _filter_leader_lines(lines.get("long_lines", []),
                                                   boxes)}
    except Exception:
        return lines


def unfuse_parallels(lines: dict, page_path: str, symbol_boxes: list) -> dict:
    gray = _gray_page(page_path)
    if gray is None:
        return lines
    try:
        from services.geometry.line_geometry import _split_parallel_lines
        skip = [tuple(s["bbox"]) for s in symbol_boxes]
        return {**lines,
                "long_lines": _split_parallel_lines(
                    gray, lines.get("long_lines", []), skip_boxes=skip)}
    except Exception:
        return lines


def _rule_fallback(metrics: dict) -> dict:
    actions = []
    if metrics["retries_used"] < 2 \
            and metrics["segments_per_symbol"] < 1.0 \
            and metrics["page_ink_density"] > 0.02 \
            and not metrics["reprompt_used"]:
        return {"verdict": "suspect", "actions": ["retry_reprompt"],
                "reason": "sparse lines on an inked page; re-scan with a stricter prompt"}
    if metrics["leader_line_candidates"] > 10:
        actions.append("drop_leaders")
    if metrics["suspected_fused_parallels"] > 3:
        actions.append("unfuse_parallels")
    actions.append("classify_styles")     # cheap; signal-line tagging default ON
    verdict = "ok" if len(actions) == 1 else "suspect"
    return {"verdict": verdict, "actions": actions,
            "reason": "refinements applied" if len(actions) > 1
            else "metrics nominal"}


def detect_node(state: ExtractionState) -> dict:
    params = {**DEFAULT_PARAMS, **(state.get("retry_params") or {}).get(STAGE, {})}
    page = state["page_paths"][0]
    emit_stage(STAGE, "running", attempt=retries_used(state, STAGE) + 1)
    result = _call_lines(
        Path(page).read_bytes(),
        symbol_boxes=state.get("symbol_detections") or [],
        base_name=state["pid"],
        output_dir=str(Path(state["hub"]) / "projects" / state["pid"] / "cache"),
        reprompt=params["reprompt"],
    )
    lines = {k: result.get(k, []) for k in
             ("long_lines", "connected_lines", "signal_lines")}
    emit_stage(STAGE, "complete",
               long=len(lines["long_lines"]),
               connected=len(lines["connected_lines"]))
    return {"line_segments": lines}


def qc_node(state: ExtractionState) -> dict:
    lines = state.get("line_segments") or {}
    symbols = state.get("symbol_detections") or []
    page = state["page_paths"][0]
    params = {**DEFAULT_PARAMS, **(state.get("retry_params") or {}).get(STAGE, {})}
    used = retries_used(state, STAGE)

    all_segs = lines.get("long_lines", []) + lines.get("connected_lines", [])
    n_segs = len(all_segs)
    leader_candidates = sum(1 for s in lines.get("long_lines", [])
                            if _seg_len(s) < 120)

    metrics = {
        "total_line_length_px": round(sum(_seg_len(s) for s in all_segs)),
        "page_ink_density": _ink_density(page),
        "segments": n_segs,
        "open_endpoints": 0,     # computed properly by the consolidation stage
        "segments_per_symbol": round(n_segs / len(symbols), 2) if symbols else 0.0,
        "suspected_fused_parallels": 0,   # cheap heuristic TBD; classifier is opt-in
        "leader_line_candidates": leader_candidates,
        "reprompt_used": params["reprompt"],
        "retries_used": used,
    }

    decision, controller, usage = run_controller(
        LINE_QC_V1, metrics, _rule_fallback,
        allowed_actions=ALLOWED_ACTIONS, stage=STAGE,
        use_llm=bool(state.get("provider")))

    actions = decision.get("actions") or [decision.get("action", "proceed")]
    actions = [a for a in actions if a in ALLOWED_ACTIONS] or ["proceed"]
    reason = decision.get("reason", "")

    if "retry_reprompt" in actions and not can_retry(state, STAGE):
        actions = [a for a in actions if a != "retry_reprompt"] \
            or ["proceed"]
        reason = f"{reason} (retry budget exhausted)".strip()

    updates: dict = {}
    if usage:
        updates["usage"] = [usage]

    if "retry_reprompt" in actions:
        updates["retry_counts"] = {STAGE: used + 1}
        updates["retry_params"] = {STAGE: {"reprompt": True}}
        emit_stage(STAGE, "retrying", action="retry_reprompt",
                   reason=reason)
        applied = "retry_reprompt"
    else:
        refined = lines
        for a in actions:
            if a == "drop_leaders":
                refined = drop_leaders(refined, symbols)
            elif a == "unfuse_parallels":
                refined = unfuse_parallels(refined, page, symbols)
            elif a == "classify_styles":
                refined = classify_styles(refined, page)
        if refined is not lines:
            updates["line_segments"] = refined
            emit_stage(STAGE, "refined",
                       actions=[a for a in actions if a != "proceed"],
                       signal_lines=len(refined.get("signal_lines", [])))
        applied = "+".join(actions)

    updates["qc_reports"] = [qc_report(
        STAGE, decision.get("verdict", "ok"), metrics, applied, reason,
        controller)]
    return updates


def _ink_density(page_path: str) -> float:
    gray = _gray_page(page_path)
    if gray is None:
        return 0.0
    return round(float((gray < 240).mean()), 4)


def _route_after_qc(state: ExtractionState) -> str:
    last = (state.get("qc_reports") or [{}])[-1]
    if last.get("stage") == STAGE and \
            last.get("action_taken") == "retry_reprompt":
        return "detect"
    return END


def build_line_agent():
    g = StateGraph(ExtractionState)
    g.add_node("detect", detect_node)
    g.add_node("qc", qc_node)
    g.add_edge(START, "detect")
    g.add_edge("detect", "qc")
    g.add_conditional_edges("qc", _route_after_qc, {"detect": "detect", END: END})
    return g.compile()

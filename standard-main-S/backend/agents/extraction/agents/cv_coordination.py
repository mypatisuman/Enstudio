"""CV Coordination Agent — consolidation of the three detection outputs.

Scheduling (serial YOLO -> parallel OCR+U-Net, LLM-A early start) lives
in the supervisor's edge topology; this agent owns the consolidation
step: segment normalization, symbol snapping, degenerate filtering, and
the coherence decision before connectivity building.
"""
from __future__ import annotations

from agents.extraction.state import ExtractionState
from agents.streaming import stage as emit_stage
from agents.toolkit import qc_report, run_controller
from agents.extraction.prompts.catalog import CV_CONSOLIDATION_V1

STAGE = "cv_consolidation"
ALLOWED_ACTIONS = {"proceed", "redispatch"}


def _rule_fallback(metrics: dict) -> dict:
    # Redispatch is deliberately conservative: only when one modality's own
    # QC said "failed" and budget remains. Weak-but-present data proceeds —
    # the geometric stage reports uncertainty and the vision audit compensates.
    verdicts = metrics.get("stage_verdicts") or {}
    for target in ("symbol", "text", "line"):
        stage_key = f"{target}_detection"
        if verdicts.get(stage_key) == "failed" and \
                (metrics.get("retries_used") or {}).get(stage_key, 0) < 2:
            return {"action": "redispatch", "redispatch_target": target,
                    "reason": f"{stage_key} failed with retry budget left"}
    return {"action": "proceed", "redispatch_target": None,
            "reason": "bundle coherent enough for connectivity"}


def consolidate_node(state: ExtractionState) -> dict:
    symbols = state.get("symbol_detections") or []
    lines = state.get("line_segments") or {}
    size = state.get("image_size") or {}
    img_w, img_h = size.get("width", 1) or 1, size.get("height", 1) or 1

    seg_dicts: list = []
    removed = 0
    snapped = lines
    try:
        from extraction_cli.image import (_filter_degenerate_segments,
                                          _segs_to_dicts,
                                          _snap_segments_to_symbols)
        seg_dicts = _segs_to_dicts(lines.get("long_lines", []),
                                   lines.get("connected_lines", []),
                                   lines.get("signal_lines", []))
        seg_dicts = _snap_segments_to_symbols(seg_dicts, symbols)
        seg_dicts, removed = _filter_degenerate_segments(
            seg_dicts, symbols, img_w, img_h)
    except Exception as e:
        emit_stage(STAGE, "partial", detail=str(e)[:200])

    snap_rate = 0.0
    if seg_dicts:
        n_snapped = sum(1 for s in seg_dicts
                        if s.get("snap_from") or s.get("snap_to")
                        or s.get("snapped"))
        snap_rate = round(n_snapped / len(seg_dicts), 3)

    verdicts = {}
    for r in state.get("qc_reports") or []:
        verdicts[r.get("stage")] = r.get("verdict")

    metrics = {
        "snap_rate": snap_rate,
        "degenerate_segments_removed": removed,
        "symbols_with_no_text": max(
            0, len(symbols) - len(state.get("text_detections") or [])),
        "symbols_with_no_lines": 0,   # refined by the geometric stage
        "stage_verdicts": verdicts,
        "retries_used": state.get("retry_counts") or {},
    }

    decision, controller, usage = run_controller(
        CV_CONSOLIDATION_V1, metrics, _rule_fallback,
        allowed_actions=ALLOWED_ACTIONS, stage=STAGE,
        use_llm=bool(state.get("provider")))

    emit_stage(STAGE, "complete", segments=len(seg_dicts),
               snap_rate=snap_rate, action=decision["action"])

    action = decision["action"]
    redispatches = (state.get("retry_counts") or {}).get("cv_redispatch", 0)
    if action == "redispatch" and redispatches >= 1:
        # One-shot guard: a second redispatch request proceeds instead —
        # the audit stage compensates, and the run never loops.
        action = "proceed"

    updates: dict = {
        "line_segments": {**lines, "consolidated": seg_dicts},
        "qc_reports": [qc_report(
            STAGE, "ok" if action == "proceed" else "suspect",
            {k: v for k, v in metrics.items() if k != "retries_used"},
            action, decision.get("reason", ""), controller)],
    }
    if action == "redispatch":
        updates["retry_counts"] = {"cv_redispatch": redispatches + 1}
    if usage:
        updates["usage"] = [usage]
    return updates


def route_after_consolidation(state: ExtractionState) -> str:
    """Supervisor routing helper (kept here with the decision logic)."""
    last = [r for r in (state.get("qc_reports") or [])
            if r.get("stage") == STAGE]
    if last and last[-1].get("action_taken") == "redispatch":
        # Redispatch currently maps to re-running the failed specialist once;
        # the supervisor wires only the conservative symbol re-run for now.
        return "redispatch"
    return "proceed"

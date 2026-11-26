"""Symbol Detection Agent.

Subgraph: detect -> qc -> (retry detect | done)

The detection core is services/llm_symbol_detection_service.py — a tiled
vision-LLM detector, imported lazily so this module (and the whole agents
package) loads even when no LLM provider is configured. The QC controller
is rule-based by default; the LLM controller refines the decision when a
provider is configured, constrained to the same enumerated action space.
"""
from __future__ import annotations

from pathlib import Path

from langgraph.graph import StateGraph, START, END

from agents.extraction.state import ExtractionState, can_retry, retries_used
from agents.streaming import stage as emit_stage
from agents.toolkit import box_iou, qc_report, run_controller
from agents.extraction.prompts.catalog import SYMBOL_QC_V1

STAGE = "symbol_detection"

DEFAULT_PARAMS = {"conf": 0.35, "reprompt": False, "cross_class_dedup": False}
ALLOWED_ACTIONS = {"proceed", "retry_lower_conf", "retry_reprompt",
                   "run_cross_class_dedup"}
LOW_CONF_SCORE = 0.45
CROSS_CLASS_IOU = 0.45


def _call_detection(image_bytes: bytes, base_name: str, output_dir: str | None,
                    reprompt: bool, conf: float | None) -> dict:
    """Tool boundary around services.llm_symbol_detection_service.process_detect_symbols.

    Kept as a module-level function so tests can monkeypatch it. `conf` is
    accepted for forward-compatibility; detections are filtered post-hoc by
    the caller (detect_node) rather than the service re-running with a
    different threshold, since the LLM's self-reported confidence isn't a
    tunable inference parameter the way YOLO's `conf` argument was.
    """
    from services.detection_router import resolve_backend
    process_detect_symbols = resolve_backend().detect_symbols
    result = process_detect_symbols(
        image_bytes,
        original_filename=base_name,
        output_dir=output_dir,
        reprompt=reprompt,
    )
    return result


def _page_ink_density(image_bytes: bytes) -> float:
    """Fraction of dark pixels — cheap sanity metric. 0.0 if cv2 missing."""
    try:
        import cv2
        import numpy as np
        arr = cv2.imdecode(np.frombuffer(image_bytes, np.uint8),
                           cv2.IMREAD_GRAYSCALE)
        if arr is None:
            return 0.0
        return float((arr < 240).mean())
    except Exception:
        return 0.0


def _cross_class_pairs(detections: list[dict]) -> int:
    n = 0
    for i, a in enumerate(detections):
        for b in detections[i + 1:]:
            if a.get("type") != b.get("type") and \
                    box_iou(a["bbox"], b["bbox"]) > CROSS_CLASS_IOU:
                n += 1
    return n


def _rule_fallback(metrics: dict) -> dict:
    """Deterministic QC — the behavior floor when no LLM is available."""
    if metrics["retries_used"] >= 2:
        return {"verdict": "ok", "action": "proceed",
                "reason": "retry budget exhausted; proceeding"}
    if metrics["symbols_found"] == 0 and metrics["page_ink_density"] > 0.02 \
            and metrics["conf_used"] > 0.25:
        return {"verdict": "suspect", "action": "retry_lower_conf",
                "reason": "no symbols on a non-blank page"}
    if metrics["low_conf_fraction"] > 0.5 and metrics["symbols_found"] >= 5 \
            and not metrics["reprompt_used"]:
        return {"verdict": "suspect", "action": "retry_reprompt",
                "reason": "majority low-confidence; re-scan with a stricter prompt"}
    if metrics["cross_class_overlap_pairs"] > 8:
        return {"verdict": "suspect", "action": "run_cross_class_dedup",
                "reason": "heavy cross-class overlap"}
    return {"verdict": "ok", "action": "proceed", "reason": "metrics nominal"}


def detect_node(state: ExtractionState) -> dict:
    params = {**DEFAULT_PARAMS, **(state.get("retry_params") or {}).get(STAGE, {})}
    page = state["page_paths"][0]
    image_bytes = Path(page).read_bytes()
    emit_stage(STAGE, "running", attempt=retries_used(state, STAGE) + 1,
               params={k: v for k, v in params.items() if v is not None})

    result = _call_detection(
        image_bytes,
        base_name=state["pid"],
        output_dir=str(Path(state["hub"]) / "projects" / state["pid"] / "cache"),
        reprompt=params["reprompt"],
        conf=params["conf"],
    )
    detections = result.get("detections", [])
    if params["conf"] and params["conf"] != DEFAULT_PARAMS["conf"]:
        detections = [d for d in detections if d.get("score", 1.0) >= params["conf"]]
    if params.get("cross_class_dedup"):
        detections = _dedup_cross_class(detections)

    emit_stage(STAGE, "complete", count=len(detections))
    return {
        "symbol_detections": detections,
        "image_size": result.get("image_size", {}),
    }


def _dedup_cross_class(detections: list[dict]) -> list[dict]:
    """Activate the (previously unused) cross-class dedup idea: for
    overlapping different-class boxes keep the higher score."""
    keep: list[dict] = []
    dropped: set[int] = set()
    for i, a in enumerate(detections):
        if i in dropped:
            continue
        for j in range(i + 1, len(detections)):
            if j in dropped:
                continue
            b = detections[j]
            if a.get("type") != b.get("type") and \
                    box_iou(a["bbox"], b["bbox"]) > CROSS_CLASS_IOU:
                dropped.add(j if a.get("score", 0) >= b.get("score", 0) else i)
        if i not in dropped:
            keep.append(a)
    return keep


def qc_node(state: ExtractionState) -> dict:
    detections = state.get("symbol_detections", [])
    page = state["page_paths"][0]
    params = {**DEFAULT_PARAMS, **(state.get("retry_params") or {}).get(STAGE, {})}
    used = retries_used(state, STAGE)

    metrics = {
        "symbols_found": len(detections),
        "page_ink_density": round(_page_ink_density(Path(page).read_bytes()), 4),
        "low_conf_fraction": round(
            sum(1 for d in detections if d.get("score", 1.0) < LOW_CONF_SCORE)
            / len(detections), 3) if detections else 0.0,
        "cross_class_overlap_pairs": _cross_class_pairs(detections),
        "reprompt_used": params["reprompt"],
        "conf_used": params["conf"],
        "retries_used": used,
    }

    decision, controller, usage = run_controller(
        SYMBOL_QC_V1, metrics, _rule_fallback,
        allowed_actions=ALLOWED_ACTIONS, stage=STAGE,
        use_llm=bool(state.get("provider")),
    )

    action = decision["action"]
    reason = decision.get("reason", "")
    if action != "proceed" and not can_retry(state, STAGE):
        # Hard wall: budget exhausted — the action is forced to proceed so
        # the router below can never loop.
        reason = f"{reason} (retry budget exhausted; forced proceed)".strip()
        action = "proceed"

    updates: dict = {
        "qc_reports": [qc_report(STAGE, decision.get("verdict", "ok"), metrics,
                                 action, reason, controller)],
    }
    if usage:
        updates["usage"] = [usage]

    if action != "proceed":
        retry_params = dict(params)
        if action == "retry_lower_conf":
            retry_params["conf"] = 0.25
        elif action == "retry_reprompt":
            retry_params["reprompt"] = True
        elif action == "run_cross_class_dedup":
            retry_params["cross_class_dedup"] = True
        updates["retry_counts"] = {**(state.get("retry_counts") or {}),
                                   STAGE: used + 1}
        updates["retry_params"] = {**(state.get("retry_params") or {}),
                                   STAGE: retry_params}
        emit_stage(STAGE, "retrying", action=action, reason=reason)
    return updates


def _route_after_qc(state: ExtractionState) -> str:
    last = (state.get("qc_reports") or [{}])[-1]
    if last.get("stage") == STAGE and last.get("action_taken") != "proceed":
        return "detect"
    return END


def build_symbol_agent():
    g = StateGraph(ExtractionState)
    g.add_node("detect", detect_node)
    g.add_node("qc", qc_node)
    g.add_edge(START, "detect")
    g.add_edge("detect", "qc")
    g.add_conditional_edges("qc", _route_after_qc, {"detect": "detect", END: END})
    return g.compile()

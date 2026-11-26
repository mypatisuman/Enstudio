"""Text Detection Agent — vision-LLM tag reading around detected symbols.

Subgraph: detect -> qc -> (retry detect | done)
Tool core: services/llm_text_detection_service.py — no OCR engine, no
ocr_corrector.py; every read is a vision-LLM call (see that module's
docstring for why the regex digit-correction step was dropped). Retry
mechanism: the service reads crop pad / upscale from module constants, so
retry_bigger_crops temporarily overrides them for the call, same as before.
"""
from __future__ import annotations

from pathlib import Path

from langgraph.graph import StateGraph, START, END

from agents.extraction.state import ExtractionState, can_retry, retries_used
from agents.streaming import stage as emit_stage
from agents.toolkit import qc_report, run_controller
from agents.extraction.prompts.catalog import TEXT_QC_V1

STAGE = "text_detection"
DEFAULT_PARAMS = {"crop_pad": None, "crop_upscale": None}   # None = service defaults
ALLOWED_ACTIONS = {"proceed", "retry_bigger_crops", "escalate_to_vision"}


def _call_ocr(image_bytes: bytes, symbol_boxes: list, base_name: str,
              output_dir: str | None, crop_pad: int | None,
              crop_upscale: float | None) -> dict:
    """Tool boundary. Overrides service module constants for the duration
    of the call when retry params are set (restored in finally)."""
    import importlib

    from services.detection_router import resolve_backend
    backend = resolve_backend()
    # The crop-pad / upscale retry knobs are module constants on whichever
    # text service is active. Resolve that module from the engine rather than
    # always poking the LLM one, so a "retry_bigger_crops" decision still has
    # an effect when the CV engine is selected.
    tds = importlib.import_module("services.llm_text_detection_service")
    saved = {}
    try:
        if crop_pad is not None and hasattr(tds, "_CROP_PAD"):
            saved["_CROP_PAD"] = tds._CROP_PAD
            tds._CROP_PAD = crop_pad
        if crop_upscale is not None and hasattr(tds, "_CROP_UPSCALE"):
            saved["_CROP_UPSCALE"] = tds._CROP_UPSCALE
            tds._CROP_UPSCALE = crop_upscale
        return backend.detect_text(
            image_bytes, symbol_boxes=symbol_boxes,
            output_dir=output_dir, base_name=base_name)
    finally:
        for k, v in saved.items():
            setattr(tds, k, v)


def _requires_tag_types() -> set:
    try:
        from services.llm_text_detection_service import _REQUIRES_ISA_TAG
        return set(_REQUIRES_ISA_TAG)
    except Exception:
        return set()


def _rule_fallback(metrics: dict) -> dict:
    if metrics["retries_used"] >= 2:
        return {"verdict": "ok", "action": "proceed",
                "reason": "retry budget exhausted; proceeding"}
    if metrics["fallback_fraction"] > 0.25:
        return {"verdict": "suspect", "action": "retry_bigger_crops",
                "reason": "high OCR fallback rate; widening crops"}
    if 0.10 <= metrics["fallback_fraction"] <= 0.25:
        return {"verdict": "suspect", "action": "escalate_to_vision",
                "reason": "moderate fallback rate; targeted vision read"}
    return {"verdict": "ok", "action": "proceed", "reason": "metrics nominal"}


def detect_node(state: ExtractionState) -> dict:
    params = {**DEFAULT_PARAMS, **(state.get("retry_params") or {}).get(STAGE, {})}
    page = state["page_paths"][0]
    emit_stage(STAGE, "running", attempt=retries_used(state, STAGE) + 1)
    result = _call_ocr(
        Path(page).read_bytes(),
        symbol_boxes=state.get("symbol_detections") or [],
        base_name=state["pid"],
        output_dir=str(Path(state["hub"]) / "projects" / state["pid"] / "cache"),
        crop_pad=params["crop_pad"],
        crop_upscale=params["crop_upscale"],
    )
    texts = result.get("texts", [])
    emit_stage(STAGE, "complete", count=len(texts))
    return {"text_detections": texts}


def qc_node(state: ExtractionState) -> dict:
    texts = state.get("text_detections") or []
    symbols = state.get("symbol_detections") or []
    used = retries_used(state, STAGE)
    req_types = _requires_tag_types()
    requiring = [s for s in symbols if s.get("type") in req_types] or symbols

    # A "fallback" tag is one that equals its symbol's detected type —
    # the service's marker for an illegible/absent read (see text_read.md).
    class_names = {s.get("type") for s in symbols}
    fallbacks = [t for t in texts if t.get("text") in class_names]
    unreadable = [{"symbol_id": f"n{i+1}", "type": t.get("nearest_symbol", ""),
                   "bbox": t.get("bbox")}
                  for i, t in enumerate(fallbacks)][:20]

    metrics = {
        "symbols_requiring_tags": len(requiring),
        "tags_read": len(texts) - len(fallbacks),
        "fallback_to_class_name": len(fallbacks),
        "fallback_fraction": round(len(fallbacks) / len(requiring), 3)
        if requiring else 0.0,
        "unreadable_crops": unreadable,
        "retries_used": used,
    }

    decision, controller, usage = run_controller(
        TEXT_QC_V1, metrics, _rule_fallback,
        allowed_actions=ALLOWED_ACTIONS, stage=STAGE,
        use_llm=bool(state.get("provider")))

    action = decision["action"]
    reason = decision.get("reason", "")
    if action == "retry_bigger_crops" and not can_retry(state, STAGE):
        reason = f"{reason} (retry budget exhausted; forced proceed)".strip()
        action = "proceed"

    updates: dict = {
        "qc_reports": [qc_report(STAGE, decision.get("verdict", "ok"),
                                 {k: v for k, v in metrics.items()
                                  if k != "unreadable_crops"},
                                 action, reason, controller)],
    }
    if usage:
        updates["usage"] = [usage]

    if action == "escalate_to_vision":
        # Not a retry — hand the unreadable crops to the Harness LLM A call.
        updates["text_escalations"] = unreadable
        emit_stage(STAGE, "escalating", crops=len(unreadable))
    elif action == "retry_bigger_crops":
        updates["retry_counts"] = {STAGE: used + 1}
        updates["retry_params"] = {STAGE: {"crop_pad": 80, "crop_upscale": 3.0}}
        emit_stage(STAGE, "retrying", action=action, reason=reason)
    return updates


def _route_after_qc(state: ExtractionState) -> str:
    last = (state.get("qc_reports") or [{}])[-1]
    if last.get("stage") == STAGE and \
            last.get("action_taken") == "retry_bigger_crops":
        return "detect"
    return END


def build_text_agent():
    g = StateGraph(ExtractionState)
    g.add_node("detect", detect_node)
    g.add_node("qc", qc_node)
    g.add_edge(START, "detect")
    g.add_edge("detect", "qc")
    g.add_conditional_edges("qc", _route_after_qc, {"detect": "detect", END: END})
    return g.compile()

"""Shared agent utilities.

Core principle: every LLM "controller" decision has a coded deterministic
fallback. An LLM outage degrades the system to rule-based behavior — it
never blocks the pipeline.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from agents.extraction.state import QCReport, UsageRecord


def parse_controller_json(raw: str) -> dict | None:
    """Extract the decision JSON from a controller response, using the
    same armor as the verification pipeline (utils/json_utils)."""
    try:
        from utils.json_utils import extract_json_object
        obj = extract_json_object(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def run_controller(
    prompt: str,
    metrics: dict[str, Any],
    fallback: Callable[[dict], dict],
    *,
    allowed_actions: set[str],
    stage: str,
    use_llm: bool = True,
    max_tokens: int = 400,
) -> tuple[dict, str, UsageRecord | None]:
    """Run one bounded controller decision.

    Returns (decision, controller_kind, usage). `decision` always contains
    at least {"action": ..., "reason": ...} with action in allowed_actions.
    controller_kind is "rules", "llm", or "llm_fallback_rules".
    """
    rule_decision = fallback(metrics)

    if not use_llm:
        return rule_decision, "rules", None

    try:
        from adapters.llm_factory import get_provider
        from agents.prompts import fill_prompt
        provider = get_provider()
        filled = fill_prompt(prompt, metrics)
        resp = provider.complete(filled, max_tokens=max_tokens, tier="fast")
        decision = parse_controller_json(resp.text)
        if decision is not None:
            # Schema wall: malformed decisions are treated as no decision
            # (rules fallback), never silently coerced into "proceed".
            try:
                from agents.extraction.schemas import QCDecision
                decision = {**decision,
                            **QCDecision.model_validate(decision).model_dump()}
            except Exception:
                decision = None
        usage: UsageRecord = {
            "stage": stage,
            "provider": getattr(resp, "provider", ""),
            "model": getattr(resp, "model", ""),
            "input_tokens": getattr(resp, "input_tokens", 0),
            "output_tokens": getattr(resp, "output_tokens", 0),
        }
        if decision and decision.get("action") in allowed_actions:
            decision.setdefault("reason", "")
            return decision, "llm", usage
        # Parsed but invalid action — enumerated action space is a hard wall.
        return rule_decision, "llm_fallback_rules", usage
    except Exception:
        return rule_decision, "llm_fallback_rules", None


def qc_report(stage: str, verdict: str, metrics: dict, action: str,
              reason: str, controller: str) -> QCReport:
    return {
        "stage": stage,
        "verdict": verdict,          # type: ignore[typeddict-item]
        "metrics": metrics,
        "action_taken": action,
        "reason": reason,
        "controller": controller,    # type: ignore[typeddict-item]
    }


def box_iou(a: list, b: list) -> float:
    """IoU of two [x1, y1, x2, y2] boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0

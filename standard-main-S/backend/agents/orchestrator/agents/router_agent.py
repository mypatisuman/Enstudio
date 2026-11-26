"""Application-level router agent — the single agentic entry point.

Deterministic first: a typed payload (file attached, explicit workflow)
never consults an LLM. Free-text requests use keyword rules, refined by
the LLM router (app_router.md) when a provider is configured,
constrained to the same three targets.
"""
from __future__ import annotations

import re

from agents.prompts import load_prompt
from agents.toolkit import run_controller

TARGETS = ("extraction", "describe", "health")

_KEYWORDS = [
    ("extraction", r"\b(extract|digitize|digitise|scan|ocr|process (this|the) (drawing|pdf|file))\b"),
    ("health", r"\b(health|status of|are the (models|agents)|system (ok|up|status))\b"),
]


def _rule_route(metrics: dict) -> dict:
    if metrics.get("has_file"):
        return {"action": "extraction",
                "reason": "attached drawing file always means extraction"}
    msg = (metrics.get("message") or "").lower()
    for target, pattern in _KEYWORDS:
        if re.search(pattern, msg):
            return {"action": target, "reason": f"keyword match for {target}"}
    return {"action": "describe",
            "reason": "conversational request; describe is read-safe"}


def route_request(message: str, *, has_file: bool = False,
                  use_llm: bool = True) -> tuple[str, str, str]:
    """Returns (target, reason, controller_kind)."""
    if has_file:
        # Hard rule — never spend an LLM call on this.
        return "extraction", "attached drawing file", "rules"
    metrics = {"message": message, "has_file": has_file}
    decision, controller, _usage = run_controller(
        load_prompt("app_router"), metrics, _rule_route,
        allowed_actions=set(TARGETS), stage="app_router", use_llm=use_llm)
    target = decision.get("action") or "describe"
    if target not in TARGETS:
        target = "describe"
    return target, decision.get("reason", ""), controller

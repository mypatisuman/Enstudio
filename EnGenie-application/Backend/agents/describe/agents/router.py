"""Router agent for the Describe workflow — classifies one engineer
message into exactly one specialist intent. Deterministic keyword rules
first; the LLM router (describe_router.md) refines when a provider is
configured, constrained to the same five intents.
"""
from __future__ import annotations

import re

from agents.toolkit import run_controller
from agents.describe.prompts.catalog import DESCRIBE_ROUTER_V1
from agents.describe.services import repository as R

INTENTS = ("authoring", "update", "deletion", "validation", "solution", "greenfield", "brownfield", "query")

_KEYWORDS = [
    ("deletion", r"\b(delete|remove|drop|get rid of|erase)\b"),
    ("validation", r"\b(validate|validation|quality|score|issues|gaps|check the drawing)\b"),
    ("greenfield", r"\b(greenfield|clean[- ]?sheet|design a new|new plant|new unit|new facility|from scratch|fresh design)\b"),
    ("brownfield", r"\b(brownfield|retrofit|tie[- ]?in|revamp|debottleneck|existing (line|pipe|plant|unit|header|drawing)|tp-\d+|add to existing|modify existing|replacement|tap into|analyze uploaded|rebuild digital|digitiz\w*|uploaded drawing|uploaded pid|drawing analysis|convert drawing|reconstruct pid)\b"),
    ("solution", r"\b(solution|design|architecture|control strategy|control philosophy|optimize loop|cascade|interlock strategy|safety architecture|feed header|feed train|reactor train|spine|subsystem|train \(mirror\)|mirror train)\b"),
    ("update", r"\b(rename|change|update|move|relocate|reclassify|correct|set the)\b"),
    ("authoring", r"\b(add|create|connect|insert|draw|build|put|place|install)\b"),
    ("query", r"\b(what|which|where|how|list|find|show|explain|summari[sz]e|tell me)\b"),
]


def _rule_route(metrics: dict) -> dict:
    msg = (metrics.get("message") or "").lower()
    for intent, pattern in _KEYWORDS:
        if re.search(pattern, msg):
            return {"intent": intent, "action": intent,
                    "reason": f"keyword match for {intent}"}
    return {"intent": "query", "action": "query",
            "reason": "no action verb found; defaulting to read-only query"}


def safe_summary(pid: str) -> str:
    try:
        return R.graph_summary(pid)
    except Exception as e:
        return f"(graph summary unavailable: {str(e)[:100]})"


#: Wording that means "add to or change the existing plant's instrumentation".
_RETROFIT_HINT = re.compile(
    r"\b(sub-?systems?|systems?|instrument(ation)? packages?|accessor(y|ies)|"
    r"tie[- ]?in|tie into|retrofit|revamp|"
    r"(pressure|temperature|flow|level)( control)? (loops?|transmitters?|instruments?|"
    r"measurements?|indicators?|packages?))\b", re.IGNORECASE)


def _digitised(pid: str) -> bool:
    try:
        return bool(R.digitisation_status(pid).get("digitised"))
    except Exception:
        return False


def state_aware_intent(pid: str, message: str, intent: str) -> tuple[str, str | None]:
    """Re-route design wording by project state.

    Keyword routing alone sent "add a transmitter to the feed subsystem" to
    the solution agent and "add instruments to the reactor system" to
    authoring, so retrofits of a digitised drawing skipped the brownfield
    agent and its duplicate and hierarchy checks. When the project already
    holds a digitised drawing, instrumentation added to systems, subsystems or
    existing lines is a retrofit. A clean-sheet greenfield request stays
    greenfield regardless.
    """
    if intent != "greenfield" and intent != "brownfield" and _wants_digitisation(pid, message):
        return "brownfield", "request to digitise the uploaded drawing"
    if intent not in ("authoring", "solution") or not _RETROFIT_HINT.search(message or ""):
        return intent, None
    if _digitised(pid):
        return "brownfield", "digitised drawing + instrumentation/subsystem wording"
    return intent, None


def _wants_digitisation(pid: str, message: str) -> bool:
    """"Analyze the uploaded drawing and rebuild the P&ID" is a brownfield
    job. The LLM router called it authoring (new elements are created), and
    the completeness gate then asked for fluid properties and trays."""
    try:
        from domain.solution.services.brownfield_vision_service import (
            is_vision_rebuild_request, resolve_uploaded_drawing)
        if not is_vision_rebuild_request(message or ""):
            return False
        return resolve_uploaded_drawing(pid)[0] is not None
    except Exception:
        return False


def route_message(pid: str, message: str,
                  *, use_llm: bool = True) -> tuple[str, str, str]:
    """Returns (intent, reason, controller_kind)."""
    metrics = {"message": message, "graph_summary": safe_summary(pid),
               "digitised": "yes" if _digitised(pid) else "no"}
    decision, controller, _usage = run_controller(
        DESCRIBE_ROUTER_V1, metrics, _rule_route,
        allowed_actions=set(INTENTS), stage="describe_router",
        use_llm=use_llm)
    intent = decision.get("intent") or decision.get("action") or "query"
    if intent not in INTENTS:
        intent = "query"
    reason = decision.get("reason", "")
    intent, override = state_aware_intent(pid, message, intent)
    if override:
        reason = f"{reason}; routed to brownfield: {override}".strip("; ")
    return intent, reason, controller

"""Input analysis for every Describe chat message.

Each message is one of:
    build      create or design: greenfield design, digitise an uploaded drawing,
               add elements, retrofit
    update     change what exists: rename, move, reconnect, delete
    question   ask about the P&ID that was built (answered by retrieval)
    mixed      a change AND a question ("add PT-102 on V-101 and tell me what
               else taps that line"), split into ordered steps
    chat       greetings / thanks (answered by the question path)

and is rewritten as a STANDALONE request using the chat memory, so a
follow-up ("and its controller?", "delete that one") names its tags.

Rules decide first (offline, instant); the LLM refines with the memory and
the drawing in view when a provider is available. Either way the result has
the same shape:
    {"mode", "steps": [{"kind": "change"|"question", "message"}],
     "standalone", "referenced_tags", "reason", "method"}
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

MODES = ("build", "update", "question", "mixed", "chat")
_MODE_PREFIX = re.compile(r"^\[mode:[^\]]+\]\s*", re.IGNORECASE)
TAG_RE = re.compile(r"\b[A-Z]{1,5}-\d{1,6}[A-Z]?(?:-\d+)?\b")

_POLITE = r"(?:please\s+|kindly\s+|can you\s+|could you\s+|would you\s+|will you\s+|i want(?: you)? to\s+|" \
          r"i need(?: you)? to\s+|i'd like(?: you)? to\s+|let's\s+|lets\s+|go ahead and\s+|now\s+|then\s+|also\s+|and\s+)*"
_BUILD_VERBS = (r"add|create|insert|connect|draw|build|generate|design|place|put|install|make|digiti[sz]e|extract|"
                r"retrofit|tie[- ]?in|rebuild|reconstruct|convert|implement|develop|synthesi[sz]e|attach")
_UPDATE_VERBS = (r"rename|change|update|move|relocate|reclassify|correct|modify|edit|replace|swap|set|assign|"
                 r"reconnect|reroute|disconnect|delete|remove|drop|erase|get rid of|split|merge|break")
_CHANGE_RE = re.compile(rf"^{_POLITE}(?:{_BUILD_VERBS}|{_UPDATE_VERBS})\b", re.IGNORECASE)
_UPDATE_RE = re.compile(rf"^{_POLITE}(?:{_UPDATE_VERBS})\b", re.IGNORECASE)
_QUESTION_START = re.compile(
    r"^(?:what|what's|whats|which|where|who|whom|whose|why|how|when|is|are|was|were|does|do|did|has|have|"
    r"can|could|should|would|will|shall|may|might|explain|describe|summari[sz]e|tell me|show me|list|"
    r"give me|identify|find|count|compare|walk me through|any|are there|is there|validate|verify|check|audit|"
    r"score|review)\b", re.IGNORECASE)
_HOW_TO = re.compile(r"^(?:how (?:do|can|should|would) (?:i|we)|what if|why)\b", re.IGNORECASE)
_DIRECT_BUILD = ("build solution on canvas", "build canvas", "build from image", "extract and build",
                 "generate p&id", "build now")
_CHAT = re.compile(r"^(?:hi|hello|hey|thanks|thank you|ok|okay|great|cool|good|nice|bye)\b[\s!.]*$", re.IGNORECASE)
_PRONOUN = re.compile(r"\b(?:it|its|it's|this|that|these|those|them|they|their|the same|same one|that one|this one|"
                      r"the former|the latter)\b", re.IGNORECASE)
_SPLIT = re.compile(r"(?<=[?!.;])\s+|\s+(?:and then|then|and also|also)\s+|"
                    r"\s+and\s+(?=(?:what|which|where|why|how|tell|show|explain|list|is|are|does|do)\b)",
                    re.IGNORECASE)


def clean(message: str) -> str:
    return _MODE_PREFIX.sub("", (message or "").strip()).strip()


def _segment_kind(seg: str) -> str | None:
    s = seg.strip().strip(",")
    if not s:
        return None
    if _HOW_TO.match(s):
        return "question"
    if _CHANGE_RE.match(s):
        return "change"
    if s.endswith("?") or _QUESTION_START.match(s):
        # "can you add ..." already matched as a change above
        return "question"
    return None


def _resolve_refs(text: str, focus: list[str]) -> str:
    """A step without a tag that points back ("its controller", "delete that one")
    names the tag the chat is about."""
    if focus and not TAG_RE.search(text.upper()) and _PRONOUN.search(text):
        return f"{text} (referring to {focus[0]})"
    return text


def analyze_rules(message: str, focus: list[str] | None = None) -> dict:
    msg = clean(message)
    low = msg.lower()
    focus = focus or []
    if any(p in low for p in _DIRECT_BUILD) or low in ("proceed", "build", "generate p&id"):
        return _result("build", [("change", msg)], msg, "direct build command", "rules")
    if _CHAT.match(msg):
        return _result("chat", [("question", msg)], msg, "small talk", "rules")
    segments = [s for s in _SPLIT.split(msg) if s and s.strip()]
    steps: list[tuple[str | None, str]] = []
    for seg in segments:
        kind = _segment_kind(seg) or (steps[-1][0] if steps else None)
        if steps and steps[-1][0] == kind:
            steps[-1] = (kind, f"{steps[-1][1]} {seg.strip()}")
        else:
            steps.append((kind, seg.strip()))
    explicit = bool(steps) and all(k is not None for k, _ in steps)
    if not steps or all(k is None for k, _ in steps):
        # no verb and no question form: a design description ("a separator with level
        # control") - the change path's router decides, and falls back to query
        kind = "question" if msg.endswith("?") else "change"
        steps = [(kind, msg)]
    resolved = []
    for k, m in steps:
        # a reference points first at a tag named earlier in the same message
        earlier = [t for _k, prev in resolved for t in TAG_RE.findall(prev.upper())]
        resolved.append((k or "change", _resolve_refs(m, list(reversed(earlier)) + focus)))
    steps = resolved
    kinds = {k for k, _ in steps}
    if kinds == {"question"}:
        mode = "question"
    elif kinds == {"change"}:
        mode = "update" if all(_UPDATE_RE.match(clean(m)) for _k, m in steps) else "build"
    else:
        mode = "mixed"
    standalone = " ".join(m for _k, m in steps) if len(steps) > 1 else steps[0][1]
    out = _result(mode, steps, standalone, f"rules: {', '.join(k for k, _ in steps)}", "rules")
    # sure enough to skip the LLM: one step, read from an explicit verb or question
    # form, and nothing pointing back at earlier turns
    out["confident"] = len(steps) == 1 and explicit and not _PRONOUN.search(msg)
    return out


def _result(mode, steps, standalone, reason, method) -> dict:
    return {"mode": mode, "steps": [{"kind": k, "message": m} for k, m in steps],
            "standalone": standalone, "referenced_tags": list(dict.fromkeys(TAG_RE.findall(standalone.upper()))),
            "reason": reason, "method": method, "confident": False}


def _analyze_llm(prompt: str) -> str | None:
    """Module-level for testability."""
    try:
        from adapters.llm_factory import get_provider
        return get_provider().complete(prompt, max_tokens=500, tier="fast").text
    except Exception as exc:
        logger.debug("[turn_analysis] LLM unavailable: %s", exc)
        return None


def _valid(parsed: dict | None) -> dict | None:
    if not isinstance(parsed, dict) or parsed.get("mode") not in MODES:
        return None
    steps = []
    for s in parsed.get("steps") or []:
        if isinstance(s, dict) and s.get("kind") in ("change", "question") and str(s.get("message") or "").strip():
            steps.append((s["kind"], str(s["message"]).strip()))
    if not steps or len(steps) > 4:
        return None
    standalone = str(parsed.get("standalone") or " ".join(m for _k, m in steps)).strip()
    mode = parsed["mode"]
    kinds = {k for k, _ in steps}
    if len(kinds) > 1:
        mode = "mixed"
    elif mode == "mixed":
        mode = "question" if kinds == {"question"} else "build"
    return _result(mode, steps, standalone, str(parsed.get("reason") or "llm"), "llm")


def analyze_turn(pid: str, message: str, *, memory_context: str = "", focus: list[str] | None = None,
                 graph_summary: str = "", use_llm: bool = True) -> dict:
    """Classify one message and rewrite it as standalone steps."""
    rules = analyze_rules(message, focus)
    if not use_llm or rules["reason"] in ("direct build command", "small talk") or rules.get("confident"):
        return rules
    from agents.describe.prompts.catalog import DESCRIBE_TURN_ANALYSIS_V1
    from agents.prompts import fill_prompt
    from agents.toolkit import parse_controller_json
    prompt = fill_prompt(DESCRIBE_TURN_ANALYSIS_V1, {
        "message": clean(message), "memory": memory_context or "(new chat - nothing yet)",
        "graph_summary": graph_summary or "(no drawing yet)", "rules_guess": rules["mode"]})
    raw = _analyze_llm(prompt)
    llm = _valid(parse_controller_json(raw)) if raw else None
    if llm is None:
        return rules
    return llm

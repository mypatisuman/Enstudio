"""
Deterministic routing at awaitAllSpecs (and related sidebar steps).

After the assistant prompts the user to review the sidebar and type **proceed**:
  - Short affirmatives (yes, ok, proceed, …)  → start final vendor analysis
  - Schema values / field edits               → update_agent / modification path
"""
from __future__ import annotations

import re
from typing import Literal

SIDEBAR_EDIT_STEPS = frozenset({
    "awaitAllSpecs",
    "awaitMissingInfo",
    "awaitAdditionalAndLatestSpecs",
    "awaitAdvancedSpecs",
    "showSummary",
})

SidebarChatAction = Literal["proceed", "spec_edit", "other"]

_PROCEED_TOKENS = frozenset({
    "yes", "y", "yeah", "yep", "yup", "ok", "okay", "k", "sure", "proceed",
    "continue", "go", "run", "start", "done", "confirm", "confirmed", "search",
    "analyze", "analysis", "goahead", "letsgo", "let'sgo", "lets", "let's",
    "runsearch", "startsearch", "findvendors", "vendorsearch", "submit",
})

_PROCEED_PHRASES = (
    "proceed",
    "go ahead",
    "go on",
    "run search",
    "start search",
    "find vendors",
    "run analysis",
    "start analysis",
    "looks good",
    "all good",
    "good to go",
)

_SPEC_PATTERNS = (
    re.compile(r"(?:^|\s)(?:set|change|update|make|add|remove|delete|clear)\s+", re.I),
    re.compile(r"[:=]", re.I),
    re.compile(r"\d+\s*(?:mm|cm|m|bar|psi|kpa|mpa|°c|°f|degc|degf|%|gpm|lpm|m3/h|rpm|hz|v|ma)", re.I),
    re.compile(r"\b(?:accuracy|range|pressure|temperature|material|ip\s*\d+|nema|hart|ff|profibus|modbus)\b", re.I),
    re.compile(r"(?:mandatory|optional|advanced)requirements\.", re.I),
    re.compile(r"\bIP\s*\d+\b", re.I),
)


def _is_bare_proceed_token(text: str) -> bool:
    compact = _normalize_compact(text)
    if compact in _PROCEED_TOKENS:
        return True
    tokens = re.findall(r"[a-z']+", text.lower())
    return bool(tokens) and all(t in _PROCEED_TOKENS for t in tokens) and len(compact) <= 24


def looks_like_spec_update(user_input: str) -> bool:
    """True when message is likely a schema field value or edit, not bare proceed."""
    text = (user_input or "").strip()
    if not text or _is_bare_proceed_token(text):
        return False
    if any(p.search(text) for p in _SPEC_PATTERNS) or "," in text or ";" in text:
        return True
    compact = _normalize_compact(text)
    if re.search(r"\d", text) and compact not in _PROCEED_TOKENS:
        return True
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return len(tokens) >= 3 or (len(tokens) == 2 and compact not in _PROCEED_TOKENS)


def _normalize_compact(text: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", (text or "").lower())


def is_proceed_command(user_input: str) -> bool:
    """
    True for short affirmatives after the sidebar-ready message (yes, ok, proceed, …).
    Spec-shaped messages are never treated as proceed.
    """
    text = (user_input or "").strip()
    if not text or looks_like_spec_update(text):
        return False

    lower = text.lower().strip()
    if any(lower == pr or lower.startswith(pr + ".") or lower.startswith(pr + "!") for pr in _PROCEED_PHRASES):
        return True

    return _is_bare_proceed_token(text)


def resolve_sidebar_chat_action(user_input: str, current_step: str) -> SidebarChatAction:
    """
    Decide how to handle chat at sidebar review steps.

    Priority:
      1. Explicit proceed affirmatives → vendor analysis
      2. Spec-like content → modification / context update
      3. At awaitAllSpecs, default unknown text → spec edit (try to map values)
    """
    if current_step not in SIDEBAR_EDIT_STEPS:
        return "other"

    if is_proceed_command(user_input):
        return "proceed"

    if looks_like_spec_update(user_input):
        return "spec_edit"

    if current_step == "awaitAllSpecs":
        return "spec_edit"

    return "other"

"""
Reusable grounding / provenance validation.

A value is "grounded" when it can be traced back to a source — either source
document text (text provenance) or an allowed set of known values (membership).
Used to reject LLM-inferred / hallucinated values so only source-backed data
flows downstream.

Pure module: no LLM/DB/infra imports — safe to import and unit-test anywhere.

Two grounding primitives:
  * TEXT provenance  — `is_text_grounded`, `filter_grounded_mapping`,
                       `filter_grounded_sequence` (value must appear in source text).
  * SET membership   — `filter_grounded_in_set` (value must match one of an allowed
                       set, e.g. a retrieved candidate-product list — drops
                       hallucinated products).
"""
from typing import Any, Callable, Iterable
import re

_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
_SEPARATORS_RE = re.compile(r"[–—\-/_,;:()\[\]{}]")
_PROVENANCE_TAGS = ("[STANDARD]", "[INFERRED]")


def normalize_for_grounding(text: Any) -> str:
    """Lowercase and flatten range/unit separators so reformatted values still
    match the words actually present in the source."""
    flattened = _SEPARATORS_RE.sub(" ", str(text).lower())
    return re.sub(r"\s+", " ", flattened).strip()


def significant_tokens(value: Any) -> list[str]:
    """Distinctive tokens of a value: numbers, and alpha words >= 4 chars.

    Short unit tokens ("mm", "dc", "ss") are too common to prove provenance on
    their own, so they are not *required* to be present.
    """
    tokens = _TOKEN_RE.findall(normalize_for_grounding(value))
    return [t for t in tokens if t[0].isdigit() or len(t) >= 4]


def is_value_grounded(value: Any, normalized_source: str) -> bool:
    """True if *value* can be traced to *normalized_source* (already normalized
    via `normalize_for_grounding`). Strongest-first: whole-value substring, then
    all-distinctive-tokens-present."""
    val = str(value)
    for tag in _PROVENANCE_TAGS:
        val = val.replace(tag, "")
    val = val.strip()
    norm_val = normalize_for_grounding(val)
    if not norm_val:
        return False
    if norm_val in normalized_source:
        return True
    sig = significant_tokens(val)
    if not sig:
        return False
    return all(tok in normalized_source for tok in sig)


def is_text_grounded(value: Any, source_text: str) -> bool:
    """Convenience: normalize *source_text* then check a single value."""
    return is_value_grounded(value, normalize_for_grounding(source_text))


def filter_grounded_mapping(mapping: dict, source_text: str) -> tuple[dict, list]:
    """Split a {key: value} mapping into (grounded, dropped_keys) against text."""
    if not mapping or not source_text:
        return mapping, []
    norm = normalize_for_grounding(source_text)
    grounded: dict = {}
    dropped: list = []
    for key, val in mapping.items():
        if is_value_grounded(val, norm):
            grounded[key] = val
        else:
            dropped.append(key)
    return grounded, dropped


def filter_grounded_sequence(items: Iterable, source_text: str) -> tuple[list, list]:
    """Split a sequence of values into (grounded, dropped) against text."""
    items = list(items or [])
    if not items or not source_text:
        return items, []
    norm = normalize_for_grounding(source_text)
    kept: list = []
    dropped: list = []
    for it in items:
        if is_value_grounded(it, norm):
            kept.append(it)
        else:
            dropped.append(it)
    return kept, dropped


def filter_grounded_in_set(
    items: Iterable,
    allowed: Iterable,
    key_fn: Callable[[Any], Any] = lambda x: x,
) -> tuple[list, list]:
    """Membership grounding: keep items whose key matches one of *allowed* values.

    Reuses the token-grounding logic against the concatenated allowed values, so a
    product like "STD850" is kept when the candidate set contains
    "Honeywell STD850 Pressure Transmitter". Items whose key is not traceable to
    any allowed value are dropped (e.g. hallucinated vendor products).

    If *allowed* is empty we cannot disprove membership, so items are kept.
    Returns (kept, dropped).
    """
    items = list(items or [])
    allowed_text = " | ".join(str(a) for a in (allowed or []) if str(a).strip())
    if not items:
        return [], []
    if not allowed_text:
        return items, []  # cannot verify -> keep
    norm = normalize_for_grounding(allowed_text)
    kept: list = []
    dropped: list = []
    for it in items:
        if is_value_grounded(key_fn(it), norm):
            kept.append(it)
        else:
            dropped.append(it)
    return kept, dropped

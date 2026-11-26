"""Holistic Agent — Input Analyze & Disambiguation Gate.

Maintains backward-compatible interface forwarding to the Input Analyze Agent.
"""
from __future__ import annotations

from agents.describe.agents.input_analyze_agent import (
    STAGE,
    MAX_CLARIFICATION_ROUNDS,
    extract_tags,
    evaluate_input_holisticness,
    resolve_target,
    _format_clarifying_question,
    _extract_tags_by_regex,
    _extract_tags_llm,
    _resolve_tags,
    _tag_exists_exact,
    find_adjacent_cell_pairs,
)

__all__ = [
    "STAGE",
    "MAX_CLARIFICATION_ROUNDS",
    "extract_tags",
    "evaluate_input_holisticness",
    "resolve_target",
    "_format_clarifying_question",
    "_extract_tags_by_regex",
    "_extract_tags_llm",
    "_resolve_tags",
    "_tag_exists_exact",
    "find_adjacent_cell_pairs",
]

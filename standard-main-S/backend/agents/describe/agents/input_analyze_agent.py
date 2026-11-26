"""Input Analyze & Holistic Completeness Agent Node.

Evaluates an engineer's request BEFORE dispatch to specialists:
1. Engineering Completeness & Dependency Analysis: Evaluates completeness across
   10 engineering categories, checks dependency chains, identifies Class B Critical
   missing constraints vs Class A inferables, and determines if design can proceed.
2. Diagram Spatial Disambiguation: Extracts referenced equipment/instrument tags,
   checks existence, and verifies grid-adjacency in the 2D tile matrix.
"""
from __future__ import annotations

import re
import sys

from agents.describe.prompts.catalog import (
    DESCRIBE_INPUT_ANALYZE_V1,
    DESCRIBE_HOLISTIC_V1,
)
from agents.describe.schemas import HolisticVerdict, InputAnalysisResult, TagReferences
from agents.describe.services import repository as R
from agents.describe.services.grid_service import find_adjacent_cell_pairs
from agents.prompts import fill_prompt
from agents.retry import retryable_node
from agents.streaming import stage as emit_stage
from agents.toolkit import parse_controller_json

STAGE = "input_analyze_agent"
MAX_CLARIFICATION_ROUNDS = 2

_ISA_TAG_RE = re.compile(r'\b[A-Z]{1,5}-\d{1,5}[A-Z]?\b')


def _tag_exists_exact(pid: str, tag: str) -> bool:
    """Exact-match existence check in project graph."""
    return any(m["tag"] == tag for m in R.search_graph(pid, tag))


def _extract_tags_by_regex(pid: str, message: str) -> list[str]:
    """Deterministic fallback tag extraction."""
    seen: list[str] = []
    for m in _ISA_TAG_RE.finditer(message.upper()):
        tag = m.group(0)
        if tag not in seen and _tag_exists_exact(pid, tag):
            seen.append(tag)
    return seen


def _extract_tags_llm(message: str) -> list[str] | None:
    """Extracts tag references using LLM prompt (backward compatible)."""
    try:
        from adapters.llm_factory import get_provider
        prompt = fill_prompt(DESCRIBE_HOLISTIC_V1, {"message": message})
        resp = get_provider().complete(prompt, max_tokens=300, tier="fast")
        parsed = parse_controller_json(resp.text)
        if parsed is None:
            return None
        refs = TagReferences.ensure_compliant(parsed)
        return refs.get("tags") if isinstance(refs, dict) else refs.tags
    except Exception:
        return None


def _resolve_tags(pid: str, message: str, *,
                  use_llm: bool = True) -> tuple[list[str], str]:
    """Resolves tags using LLM first, falling back to regex."""
    if use_llm:
        h_mod = sys.modules.get("agents.describe.agents.holistic_agent")
        fn = getattr(h_mod, "_extract_tags_llm", _extract_tags_llm) if h_mod else _extract_tags_llm
        llm_tags = fn(message)
        if llm_tags is not None:
            return llm_tags, "llm"
    return _extract_tags_by_regex(pid, message), "rules"


def _analyze_input_llm(pid: str, message: str, *,
                       gate_mode: str = "ENABLED",
                       previously_asked_questions: list[str] | None = None) -> dict | None:
    """Invokes the Input Analyze LLM prompt."""
    try:
        from adapters.llm_factory import get_provider
        summary = R.graph_summary(pid) if pid else ""
        prev_q_str = "\n".join(previously_asked_questions) if previously_asked_questions else "None"
        prompt = fill_prompt(DESCRIBE_INPUT_ANALYZE_V1, {
            "message": message,
            "graph_summary": summary,
            "gate_mode": gate_mode,
            "previously_asked_questions": prev_q_str,
        })
        resp = get_provider().complete(prompt, max_tokens=800, tier="fast")
        parsed = parse_controller_json(resp.text)
        if parsed is None:
            return None
        res = InputAnalysisResult.ensure_compliant(parsed)
        if hasattr(res, "model_dump"):
            return res.model_dump()
        return dict(res)
    except Exception:
        return None


def _duplicate_count(pid: str, tag: str) -> int:
    return sum(1 for m in R.search_graph(pid, tag) if m["tag"] == tag)


def _resolve_single_tag(pid: str, tag: str, tags: list[str]) -> HolisticVerdict:
    """Ambiguous only if that tag itself is duplicated in the drawing."""
    n = _duplicate_count(pid, tag)
    if n > 1:
        matches = R.search_graph(pid, tag)
        return HolisticVerdict(
            clarity="ambiguous", tags=tags,
            candidates=[{"node_a": m["id"], "tag_a": m["tag"],
                        "area": m.get("area")} for m in matches],
            reason=f"'{tag}' appears {n} times in this project")
    return HolisticVerdict(clarity="clear", tags=tags)


def _format_clarifying_question(verdict: HolisticVerdict | dict) -> str:
    """Formats questions for spatial ambiguity or missing engineering constraints."""
    v_dict = dict(verdict) if hasattr(verdict, "keys") else (
        verdict.model_dump() if hasattr(verdict, "model_dump") else {}
    )
    questions = v_dict.get("questions") or []
    candidates = v_dict.get("candidates") or []
    reason = v_dict.get("reason") or ""

    # If engineering completeness generated questions (Class B missing)
    if questions:
        lines = [
            "I have synthesized the preliminary engineering solution architecture below.",
            "",
            "To refine the design parameters and industrial datasheets before final P&ID generation, please clarify:",
        ]
        for i, q in enumerate(questions[:4], 1):
            lines.append(f"  {i}. {q}")
        lines.append("")
        lines.append("You can answer any of these questions to refine the design, or click **Build Solution on Canvas** to construct with standard defaults.")
        return "\n".join(lines)

    # Spatial ambiguity (multiple candidate pairs or duplicate tags)
    if not candidates:
        return (f"I couldn't find where {reason}. Could you "
               "specify the area or give more detail about which one "
               "you mean?")
    lines = ["I found more than one match — which did you mean?"]
    for i, c in enumerate(candidates, 1):
        if "tag_a" in c and "tag_b" in c and c.get("node_b") is not None:
            loc = f"row {c['row']}" if c.get("row") is not None else "unplaced"
            lines.append(f"  {i}. {c['tag_a']} ↔ {c['tag_b']} ({loc})")
        else:
            area = c.get("area") or "no area set"
            lines.append(f"  {i}. {c.get('tag_a')} in {area}")
    lines.append("Reply with the number, or add more detail (e.g. the area).")
    return "\n".join(lines)


def _on_resolve_exhausted(pid: str, err: Exception) -> tuple[HolisticVerdict, str]:
    """Fail-open fallback on exhaustion."""
    emit_stage(STAGE, "failed", detail=str(err)[:200])
    return HolisticVerdict(clarity="no_target",
                           reason="disambiguation unavailable"), "rules"


@retryable_node(max_attempts=2, label=STAGE, on_exhausted=_on_resolve_exhausted)
def evaluate_input_holisticness(
    pid: str,
    message: str,
    *,
    intent: str = "authoring",
    gate_mode: str = "ENABLED",
    previously_asked_questions: list[str] | None = None,
    use_llm: bool = True
) -> tuple[HolisticVerdict, str]:
    """Evaluates engineering completeness and spatial disambiguation.
    Returns (HolisticVerdict, method).
    """
    tags, method = _resolve_tags(pid, message, use_llm=use_llm)
    detected_tags = re.findall(r'\b[A-Z0-9]{1,6}-[A-Z0-9-]+\b', message.upper())
    analysis_dict = None

    # ── 1. Completeness Evaluation Check ──────────────────────────────────────
    # greenfield/brownfield included alongside solution/authoring so a
    # clean-sheet or retrofit request is held to the same Class-B-critical
    # bar before the specialist starts inventing/authoring components —
    # see the matching _GATED_INTENTS entry in describe_workflow.py.
    if use_llm and gate_mode == "ENABLED" and \
            intent in ("solution", "authoring", "greenfield", "brownfield"):
        h_mod = sys.modules.get("agents.describe.agents.input_analyze_agent")
        fn = getattr(h_mod, "_analyze_input_llm", _analyze_input_llm) if h_mod else _analyze_input_llm
        raw_analysis = fn(
            pid, message, gate_mode=gate_mode,
            previously_asked_questions=previously_asked_questions
        )
        analysis_dict = None
        if raw_analysis is not None:
            if hasattr(raw_analysis, "model_dump"):
                analysis_dict = raw_analysis.model_dump()
            elif isinstance(raw_analysis, dict):
                analysis_dict = raw_analysis
            else:
                analysis_dict = dict(raw_analysis)

        if analysis_dict:
            scores = analysis_dict.get("engineering_completeness") or {}
            overall = scores.get("overall_score", 100)
            critical_missing = analysis_dict.get("critical_missing") or []
            questions = analysis_dict.get("questions") or []
            plant_type = analysis_dict.get("inferred_plant_type") or ""
            unit_ops = analysis_dict.get("unit_operations") or []
            ctrl_strategy = analysis_dict.get("inferred_control_strategy") or ""

            if (overall < 70 or any(cm.get("severity") == "Critical" for cm in critical_missing)) and questions:
                return HolisticVerdict(
                    clarity="blocked",
                    tags=tags,
                    reason=analysis_dict.get("reasoning") or "Critical design constraints are missing",
                    inferred_plant_type=plant_type,
                    unit_operations=unit_ops,
                    inferred_control_strategy=ctrl_strategy,
                    engineering_completeness=scores,
                    critical_missing=critical_missing,
                    questions=questions,
                    gap_resolution=analysis_dict.get("gap_resolution") or [],
                ), method

    # ── Holistic Subsystem Design & Synthesis ─────────────────────────────────
    rl_msg = message.strip().lower()
    detected_tags = re.findall(r'\b[A-Z0-9]{1,6}-[A-Z0-9-]+\b', message.upper())

    plant_type = (analysis_dict.get("inferred_plant_type") if analysis_dict else "") or ""
    unit_ops = (analysis_dict.get("unit_operations") if analysis_dict else []) or []
    ctrl_strategy = (analysis_dict.get("inferred_control_strategy") if analysis_dict else "") or ""

    # ── 2. Spatial / Tag Disambiguation ───────────────────────────────────────
    if len(tags) == 0:
        return HolisticVerdict(
            clarity="no_target",
            tags=tags,
            inferred_plant_type=plant_type,
            unit_operations=unit_ops,
            inferred_control_strategy=ctrl_strategy,
            reason="no existing-element reference found; nothing to disambiguate",
        ), method

    # Pair-adjacency ("add X between A and B") only makes sense when the
    # engineer actually placed something BETWEEN two tags. For retrofits
    # (brownfield/greenfield) two tags are usually a tie-in plus an unrelated
    # reference, and demanding that they be adjacent blocked valid requests
    # with "not directly connected anywhere". Authoring/solution keep their
    # original behaviour.
    says_between = bool(re.search(r"\bbetween\b", message, re.IGNORECASE))
    pair_query = intent in ("authoring", "solution") or says_between
    if intent in ("update", "deletion") or len(tags) == 1 or not pair_query:
        res = _resolve_single_tag(pid, tags[0], tags)
        res.inferred_plant_type = plant_type
        res.unit_operations = unit_ops
        res.inferred_control_strategy = ctrl_strategy
        return res, method

    # authoring/solution with 2+ tags: pair-adjacency ("between A and B")
    tag_a, tag_b = tags[0], tags[1]
    pairs = find_adjacent_cell_pairs(pid, tag_a, tag_b)

    if len(pairs) == 0:
        return HolisticVerdict(
            clarity="ambiguous", tags=tags,
            inferred_plant_type=plant_type,
            unit_operations=unit_ops,
            inferred_control_strategy=ctrl_strategy,
            reason=f"'{tag_a}' and '{tag_b}' are not directly connected anywhere in this project",
        ), method
    if len(pairs) == 1:
        return HolisticVerdict(
            clarity="clear", tags=tags,
            resolved_target=pairs[0],
            inferred_plant_type=plant_type,
            unit_operations=unit_ops,
            inferred_control_strategy=ctrl_strategy,
        ), method

    return HolisticVerdict(
        clarity="ambiguous", candidates=pairs, tags=tags,
        inferred_plant_type=plant_type,
        unit_operations=unit_ops,
        inferred_control_strategy=ctrl_strategy,
        reason=f"'{tag_a}' and '{tag_b}' are adjacent in {len(pairs)} different places",
    ), method


def extract_tags(pid: str, message: str, *, use_llm: bool = True) -> list[str]:
    """Public tag extraction helper."""
    tags, _ = _resolve_tags(pid, message, use_llm=use_llm)
    return tags


# Compatibility alias
resolve_target = evaluate_input_holisticness

"""
Holistic agent -- the merged Engineering Design Completeness Gate +
requirements extractor (Node 1).

One Pro-LLM call per turn evaluates whether an experienced instrumentation
engineer could produce a technically valid solution WITHOUT major engineering
assumptions -- not merely whether instruments are mentioned. The LLM extracts
and classifies engineering constraints (process, equipment, control philosophy,
instrumentation, utilities, mechanical, safety, integration, performance,
procurement), walks control-loop dependency chains (e.g. Pressure Control ->
Control Valve -> Cv -> Fluid Properties), scores completeness per category,
and lists Class B (Critical) missing constraints. PYTHON -- not the LLM --
derives the holistic verdict from those scores and criticals via configurable
thresholds (see _normalize_verdict). When complete, the SAME response carries
the full BOM extraction consumed by expansion -> infer -> format_results;
when blocked, grouped severity-sorted clarification questions are returned
instead.

Gate modes:
  ENABLED  -- run the completeness framework; questions when blocked,
              extraction when complete.
  BYPASSED -- always extract: long inputs (chunked-parallel, a global
              completeness judgment across local chunks isn't meaningful) and
              post-confirmation turns ("go ahead anyway").

Cross-turn context is memory-backed (common/ai/memory/holistic.py:
in-process L1 + MongoDB L2): the gate remembers its stage, the original
requirement, the user's follow-up answers, and every question already asked,
so it never repeats questions and extracts from the consolidated requirement.
"""

import json
import logging
import os
import re
import time
from concurrent.futures import as_completed
# Context-propagating pool: keeps benchmark run/test attribution across worker
# threads (a plain ThreadPoolExecutor loses it, undercounting benchmark tokens).
from common.monitoring.benchmarking.context import BenchmarkThreadPoolExecutor as ThreadPoolExecutor
from datetime import datetime

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from domain.orchestrator.state import AgenticSystemState
from domain.solution.services.category_service import get_relevant_categories
from domain.solution.agents.shared import (
    HOLISTIC_AGENT_PROMPT,
    llm_pro,
    _CHUNK_THRESHOLD_CHARS,
    _MAX_PARALLEL_CHUNK_WORKERS,
    _split_requirements_into_chunks,
    _parse_extraction_json,
    _merge_extraction_results,
    _trace_identification,
    _summarize_items,
)
from common.ai.llm import SOLUTION_LLM_PROVIDER, with_json_mode
from common.ai.memory import (
    clear_holistic_context,
    get_holistic_context,
    store_holistic_context,
)
from domain.solution.memory import (
    build_looped_conversation_context,
    append_node_execution_context,
)
from common.helpers.node_retry import retryable_node
from common.helpers.progress_tracker import progress_tracker

logger = logging.getLogger(__name__)

_AFFIRMATIVE_PATTERNS = (
    "yes", "yeah", "yep", "yup", "go ahead", "proceed", "continue",
    "sure", "ok", "okay", "confirm", "correct", "that's fine", "its fine",
    "it's fine", "as is", "as-is", "skip", "yes please", "please proceed",
    "please go ahead", "please continue", "all good", "looks good", "sounds good",
    "good to go", "fine", "perfect", "agreed", "approved", "accept", "accepted",
    "acknowledged", "no problem", "ready", "generate", "build", "design",
    "execute", "start", "understood", "go for it", "carry on", "do it",
    "proceed as is", "proceed with design", "absolutely", "definitely",
    "sure thing", "affirmative", "right", "alright", "all right", "got it",
    "i approve", "proceed with existing", "go on", "lets go", "let's go",
)

# "Proceed without it" phrasings that legitimately contain negation words —
# checked BEFORE the negation guard below.
_PROCEED_WITHOUT_PATTERNS = (
    "no need", "don't need", "dont need", "not needed", "without it",
    "leave as is", "ignore", "skip for now", "no worries", "not required",
    "proceed anyway", "continue anyway", "build anyway", "no additional info",
    "none for now", "nothing else", "leave it",
)

# Replies containing these are hesitation/refusal, never confirmation
# ("hmm not sure what you need" must NOT match on the "sure" substring).
_NEGATION_PATTERNS = ("not ", "n't", "unsure", "no idea", "cannot", "can not", "never")

_CONFIRM_MESSAGE = "Shall I proceed with the existing requirements?"

# Engineering-completeness decision thresholds (Python owns the holistic verdict;
# the LLM only supplies scores and the Class B critical-missing list).
#   - overall_score below this threshold blocks extraction even with no criticals.
#   - any critical_missing entry with severity "Critical" always blocks.
_COMPLETENESS_THRESHOLD = int(os.environ.get("ENGINEERING_COMPLETENESS_THRESHOLD", "70"))

# Hard convergence cap on the questioning loop: after this many ask-rounds the
# gate auto-proceeds (build + refinement window with the remaining gaps) instead
# of asking again — prevents perfectionism loops where every answered round
# surfaces newly-invented criticals.
_MAX_GATE_ASKS = int(os.environ.get("HOLISTIC_MAX_ASK_ROUNDS", "3"))


def _is_affirmative(user_input: str) -> bool:
    """Lightweight heuristic: True if user_input reads as a short affirmative reply.

    Deliberately keyword-based (no LLM call) -- this only runs on follow-up turns
    after the user has already seen either the full gap questions or the simple
    "shall I proceed?" prompt, so the reply is expected to be short and direct.
    Length guard so a genuinely new, long requirements paragraph that happens to
    start with "Yes, and additionally I also need..." is NOT swallowed as a bare
    confirmation -- long/detailed input falls through to a fresh gate evaluation.
    """
    text = (user_input or "").strip().lower()
    if not text:
        return False
    if len(text) > 60:
        return False
    # A reply carrying numbers is DATA (a gap answer like "ok here: density
    # 720 kg/m3"), never a bare confirmation — route it to gate re-evaluation.
    if any(ch.isdigit() for ch in text):
        return False
    # Explicit "proceed without it" phrasings win before the negation guard.
    if any(p in text for p in _PROCEED_WITHOUT_PATTERNS):
        return True
    # Hesitation/refusal ("not sure", "can't say") is never a confirmation,
    # even when it substring-matches an affirmative token like "sure".
    if any(n in text for n in _NEGATION_PATTERNS):
        return False
    return any(p in text for p in _AFFIRMATIVE_PATTERNS)


def _build_merged_requirement(ctx: dict, current_input: str = "") -> str:
    """Consolidate the gate conversation into one requirement text: the turn-1
    original requirement plus every follow-up answer the user has given."""
    parts: list[str] = []
    original = (ctx.get("original_requirement") or "").strip()
    if original:
        parts.append(original)
    additions = [a.strip() for a in (ctx.get("accumulated_inputs") or []) if a and a.strip()]
    current = (current_input or "").strip()
    if current:
        additions.append(current)
    if additions:
        if parts:
            parts.append("Additional information provided later:")
        parts.extend(additions)
    return "\n\n".join(parts)


def _build_conversation_context(state: AgenticSystemState) -> str:
    """Build conversation context using chronological multi-turn loop."""
    return build_looped_conversation_context(state, session_id=state.get("session_id", "default"))


def _run_combined_llm(
    state: AgenticSystemState,
    requirement_text: str,
    gate_mode: str,
    previously_asked: list[str] | None,
    conversation_context: str,
    chunk_idx: int = 0,
    chunk_total: int = 1,
    existing_bom: str = "None",
) -> dict:
    """One combined gate+extraction invocation. Returns the parsed raw dict
    (engineering_completeness/reasoning/critical_missing/questions +
    project_name/instruments/accessories/summary). Raises on LLM failure so
    callers (and @retryable_node) can retry/fail."""
    session_id = state.get("session_id", "default")
    user_id = state.get("user_id")

    prompt = ChatPromptTemplate.from_template(HOLISTIC_AGENT_PROMPT)
    # Pro is used because complex BOMs (10+ instruments) can exceed Flash's
    # 16K output token limit, causing truncated JSON.
    chain = prompt | with_json_mode(llm_pro, SOLUTION_LLM_PROVIDER) | StrOutputParser()

    invoke_vars = {
        "requirements": requirement_text,
        "conversation_context": conversation_context,
        # Embedding-shortlisted to the ~80 categories most relevant to this
        # requirement (env HOLISTIC_CATEGORY_SHORTLIST; 0 = full list) — the
        # full 460-name list cost ~2.5-3K prompt tokens on every gate call.
        "valid_categories": get_relevant_categories(requirement_text),
        "gate_mode": gate_mode,
        "previously_asked_questions": "\n".join(f"- {q}" for q in (previously_asked or [])) or "None",
        "existing_bom": existing_bom,
    }
    try:
        rendered_prompt = prompt.format(**invoke_vars)
    except Exception as render_exc:
        rendered_prompt = f"<failed to render: {render_exc}>"

    trace_meta = {
        "session_id": session_id,
        "user_id": user_id,
        "stream_id": state.get("stream_id"),
        "gate_mode": gate_mode,
        "chunk_idx": chunk_idx,
        "chunk_total": chunk_total,
        "requirements_len": len(requirement_text),
        "requirements_preview": requirement_text[:500],
        "previously_asked_count": len(previously_asked or []),
        "conversation_context_len": len(conversation_context),
    }
    _trace_identification("call_start", {**trace_meta, "rendered_prompt": rendered_prompt})

    t_start = datetime.utcnow()
    raw_response = ""
    parsed: dict = {}
    parse_error: str | None = None
    try:
        raw_response = chain.invoke(
            invoke_vars,
            config={"metadata": {"user_id": user_id, "agent_type": "solution"}},
        )
        parsed = _parse_extraction_json(raw_response)
    except Exception as pe:
        parse_error = f"{type(pe).__name__}: {pe}"
        raise
    finally:
        latency_ms = (datetime.utcnow() - t_start).total_seconds() * 1000.0
        _trace_identification("call_end", {
            **trace_meta,
            "latency_ms": round(latency_ms, 1),
            "raw_response": raw_response,
            "raw_response_len": len(raw_response or ""),
            "parse_error": parse_error,
            "overall_score": ((parsed or {}).get("engineering_completeness") or {}).get("overall_score"),
            "critical_missing_count": len((parsed or {}).get("critical_missing", []) or []),
            "questions_count": len((parsed or {}).get("questions", []) or []),
            "instrument_count": len((parsed or {}).get("instruments", []) or []),
            "accessory_count": len((parsed or {}).get("accessories", []) or []),
            "instruments": _summarize_items((parsed or {}).get("instruments", []), "instrument"),
            "accessories": _summarize_items((parsed or {}).get("accessories", []), "accessory"),
        })
        if parse_error:
            _trace_identification("parse_error", {**trace_meta, "error": parse_error, "raw_response": raw_response})
    return parsed


def _synthesize_questions_from_gaps(gaps: list[dict]) -> list[str]:
    """Build a minimal, real question per distinct category present in `gaps`
    (critical_missing) when the LLM flagged blocking gaps but returned an
    empty "questions" array. Never silently proceed to extraction while
    concrete gaps exist -- ask something grounded in what was actually
    flagged, capped at 5, mirroring the prompt's own grouping convention."""
    seen: set[str] = set()
    questions: list[str] = []
    for gap in gaps:
        category = str(gap.get("category") or "").strip()
        reason = str(gap.get("reason") or "").strip()
        if not category or category in seen:
            continue
        seen.add(category)
        if reason:
            questions.append(f"Can you provide details on {category} — {reason}")
        else:
            questions.append(f"Can you provide the missing {category} details required for this design?")
        if len(questions) >= 5:
            break
    return questions


def _normalize_verdict(parsed: dict, gate_mode: str, previously_asked: list[str] | None) -> dict:
    """Derive the holistic verdict IN PYTHON from the LLM's engineering-completeness
    output. The LLM supplies per-category scores (engineering_completeness) and the
    Class B critical-missing list; it never decides holistic directly.

    Decision rule (gate_mode ENABLED):
      holistic = no Critical-severity missing item
                 AND overall_score >= _COMPLETENESS_THRESHOLD
    BYPASSED mode forces holistic regardless of scores.

    Returns keys the node depends on:
      is_holistic, questions (max 5), gaps (the critical_missing list -- key name
      kept for downstream/memory compatibility), reasoning, scores.

    Raises ValueError when gate_mode is ENABLED/REFINEMENT and the response is
    missing "engineering_completeness" entirely -- this is a degraded/malformed
    LLM response, not a legitimate holistic verdict, and must NEVER silently
    default to proceeding. The caller runs inside @retryable_node, so raising
    here triggers a retry, and on exhaustion falls through to
    _on_analysis_failed (sets state["error"]) -- consistent with this agent's
    "no proceed-anyway degradation" policy for analysis failures.
    """
    questions = (parsed.get("questions", []) or [])[:5]
    critical_missing = parsed.get("critical_missing", []) or []
    reasoning = parsed.get("reasoning", "")
    scores = parsed.get("engineering_completeness") or {}

    if gate_mode == "BYPASSED":
        is_holistic = True
    elif scores:
        blocking = [m for m in critical_missing if str(m.get("severity", "")).lower() == "critical"]
        overall = int(scores.get("overall_score") or 0)
        is_holistic = not blocking and overall >= _COMPLETENESS_THRESHOLD
        logging.info(
            f"[HOLISTIC] Completeness verdict: overall={overall} "
            f"(threshold={_COMPLETENESS_THRESHOLD}), blocking_criticals={len(blocking)} -> holistic={is_holistic}"
        )
    else:
        # No "engineering_completeness" in an ENABLED/REFINEMENT response is a
        # degraded LLM reply, not evidence of completeness. NEVER default to
        # holistic=True here (that was the old behavior and let a malformed
        # response bypass the gate entirely) -- raise so @retryable_node retries.
        raise ValueError(
            f"[HOLISTIC] Response missing 'engineering_completeness' in gate_mode={gate_mode} "
            "-- treating as a degraded response, not an implicit pass."
        )

    if is_holistic:
        questions = []

    return {
        "is_holistic": is_holistic,
        "questions": questions,
        "gaps": critical_missing,
        "reasoning": reasoning,
        "scores": scores,
    }


# ─────────────────────────────────────────────────────────────────────────────
# REFINEMENT helpers (post-build incremental updates)
# ─────────────────────────────────────────────────────────────────────────────

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")

# BOM-relevant fields shown to the LLM in REFINEMENT mode (internal pipeline /
# taxonomy / standards bookkeeping stripped, mirroring modification_node).
_BOM_PROMPT_FIELDS = (
    "category", "product_name", "accessory_name", "quantity", "specifications",
    "strategy", "specified_vendors", "specified_model_families",
    "user_specified_standards", "skip_standards", "parent_instrument_category",
)

_REMOVAL_WORDS = ("remove", "delete", "drop ", "without the", "don't need", "dont need", "no longer need")


def _snake_keys_deep(obj):
    """Recursively convert camelCase dict keys to snake_case. The frontend
    round-trips the BOM camelCased (convert_keys_to_camel_case is recursive),
    while the whole pipeline speaks snake_case."""
    if isinstance(obj, dict):
        return {_CAMEL_RE.sub(r"\1_\2", k).lower(): _snake_keys_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_snake_keys_deep(v) for v in obj]
    return obj


def _strip_bom_for_prompt(instruments: list[dict], accessories: list[dict]) -> str:
    """Serialize the existing BOM for the REFINEMENT prompt, BOM fields only."""
    def _lean(item: dict) -> dict:
        return {k: item.get(k) for k in _BOM_PROMPT_FIELDS if item.get(k) not in (None, "", [])}

    if not instruments and not accessories:
        return "None"
    return json.dumps({
        "instruments": [_lean(i) for i in instruments],
        "accessories": [_lean(a) for a in accessories],
    }, indent=2, default=str)


def _norm_spec_key(k: str) -> str:
    return str(k).lower().replace("_", "").replace(" ", "")


def _is_tagged_value(v) -> bool:
    text = str(v).lower()
    return any(t in text for t in ("[inferred]", "[standard]", "[datasheet]"))


def _mentions_removal(user_input: str) -> bool:
    text = (user_input or "").lower()
    return any(w in text for w in _REMOVAL_WORDS)


def _merge_refinement(existing: list[dict], extracted: list[dict], name_key: str,
                      user_input: str) -> tuple[list[dict], int, int]:
    """Merge the LLM's refinement extraction into the existing BOM (Python
    safety-net over the prompt's preservation rules).

    Per matched item (category + name): keep the existing item wholesale
    (standards/taxonomy fields survive) and update only spec fields where the
    old value was [INFERRED]-tagged or the new untagged value explicitly
    differs; [STANDARD]/[DATASHEET]/user values are never replaced by tagged
    output. Unmatched existing items are KEPT unless the user's input mentions
    removal (then the LLM's drop is honoured). New items are flagged
    _newly_added. Every item gets _needs_deep_analysis = changed, which
    expansion/infer use to skip untouched items.

    Returns (merged_items, changed_count, new_count).
    """
    def _key(item: dict) -> tuple:
        return (str(item.get("category", "")).strip().lower(),
                str(item.get(name_key) or item.get("product_name") or "").strip().lower())

    existing_map = {_key(i): i for i in existing}
    merged: list[dict] = []
    changed_count = 0
    new_count = 0

    for new_item in extracted or []:
        match = existing_map.pop(_key(new_item), None)
        if match is None:
            item = dict(new_item)
            item["_newly_added"] = True
            item["_needs_deep_analysis"] = True
            merged.append(item)
            new_count += 1
            continue

        base = dict(match)
        base_specs = dict(match.get("specifications") or {})
        norm_to_key = {_norm_spec_key(k): k for k in base_specs}
        changed = False

        for k, v in (new_item.get("specifications") or {}).items():
            existing_key = norm_to_key.get(_norm_spec_key(k))
            if existing_key is None:
                base_specs[k] = v
                changed = True
                continue
            old = base_specs[existing_key]
            if str(old) == str(v):
                continue
            # An UNTAGGED new value is an explicit user statement (prompt rule 2)
            # and overrides anything — user authority beats [INFERRED]/[STANDARD]/
            # [DATASHEET]. A TAGGED new value is model/pipeline-derived and never
            # overwrites an existing value (prevents LLM re-inference churn).
            if not _is_tagged_value(v):
                base_specs[existing_key] = v
                changed = True

        new_qty = new_item.get("quantity")
        if new_qty and new_qty != base.get("quantity"):
            base["quantity"] = new_qty
            changed = True

        base["specifications"] = base_specs
        base["_needs_deep_analysis"] = changed
        if changed:
            changed_count += 1
        merged.append(base)

    # Existing items the LLM dropped: honour the drop ONLY when the user's input
    # both uses removal language AND names that specific item; otherwise
    # resurrect it unchanged (an accidental LLM omission must never lose data).
    removal_intent = _mentions_removal(user_input)
    text = (user_input or "").lower()
    for leftover in existing_map.values():
        names = [str(leftover.get("category", "")).lower(),
                 str(leftover.get(name_key) or "").lower()]
        explicitly_removed = removal_intent and any(n and n in text for n in names)
        if explicitly_removed:
            changed_count += 1
            continue
        kept = dict(leftover)
        kept["_needs_deep_analysis"] = False
        merged.append(kept)

    return merged, changed_count, new_count


def _extract_bypassed(state: AgenticSystemState, requirement_text: str, conversation_context: str) -> dict:
    """Gate-bypassed extraction, chunked-parallel for long inputs. Per-chunk
    failures degrade to {} (partial BOM survives); total failure raises."""
    chunks = (
        _split_requirements_into_chunks(requirement_text)
        if len(requirement_text) > _CHUNK_THRESHOLD_CHARS
        else [requirement_text]
    )

    if len(chunks) > 1:
        logging.info(f"[HOLISTIC] Large input ({len(requirement_text)} chars) → {len(chunks)} parallel chunks")
        chunk_results: list = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=min(len(chunks), _MAX_PARALLEL_CHUNK_WORKERS)) as executor:
            future_to_idx = {
                executor.submit(_run_combined_llm, state, chunk, "BYPASSED", None, conversation_context, idx, len(chunks)): idx
                for idx, chunk in enumerate(chunks)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    chunk_results[idx] = future.result()
                    logging.info(
                        f"[HOLISTIC] ✓ Chunk {idx+1}/{len(chunks)}: "
                        f"{len((chunk_results[idx] or {}).get('instruments', []))} instruments, "
                        f"{len((chunk_results[idx] or {}).get('accessories', []))} accessories"
                    )
                except Exception as exc:
                    logging.error(f"[HOLISTIC] ✗ Chunk {idx+1} failed: {exc}")
                    chunk_results[idx] = {}
        return _merge_extraction_results([r for r in chunk_results if r])

    single_result = _run_combined_llm(state, requirement_text, "BYPASSED", None, conversation_context)
    return _merge_extraction_results([single_result])


def _apply_extraction(state: AgenticSystemState, extraction_result: dict, conversation_context: str) -> None:
    """Write the extraction into state exactly as analyze_query did (the contract
    consumed by expansion -> infer -> format_results)."""
    session_id = state.get("session_id", "default")

    _trace_identification("merged_result", {
        "session_id": session_id,
        "user_id": state.get("user_id"),
        "stream_id": state.get("stream_id"),
        "instrument_count": len(extraction_result.get("instruments", []) or []),
        "accessory_count": len(extraction_result.get("accessories", []) or []),
        "instruments": _summarize_items(extraction_result.get("instruments", []), "instrument"),
        "accessories": _summarize_items(extraction_result.get("accessories", []), "accessory"),
    })

    # Models often emit sub_systems as loop-name strings; SolutionResponse
    # requires dicts — coerce here so the harness repair gate never fires
    # (a wasted LLM call) over this shape mismatch.
    sub_systems = [
        s if isinstance(s, dict) else {"name": str(s)}
        for s in (extraction_result.get("sub_systems") or [])
    ]
    extraction_result["sub_systems"] = sub_systems
    state["deep_analysis"] = {
        "extracted_requirements": extraction_result,
        "sub_systems": sub_systems,
        "conversation_context_used": bool(conversation_context),
    }

    num_instruments = len(extraction_result.get("instruments", []))
    num_accessories = len(extraction_result.get("accessories", []))
    logging.info(f"[HOLISTIC] Extracted {num_instruments} instruments, {num_accessories} accessories")
    if num_instruments == 0:
        logging.warning("[HOLISTIC] No instruments extracted — check prompt/LLM response")

    # Append to node-to-node context memory trail
    append_node_execution_context(
        state,
        "holistic_agent",
        f"Extracted {num_instruments} instruments and {num_accessories} accessories for project '{extraction_result.get('project_name') or 'Industrial Project'}'",
        {"instrument_count": num_instruments, "accessory_count": num_accessories, "summary": extraction_result.get("summary", "")},
    )


def _clear_clarification(state: AgenticSystemState) -> None:
    """Scrub clarification fields on proceed paths. project_intent_node's
    clarification branch may have populated them before the routing override
    sent the turn here; leaving them would surface stale questions alongside
    a successful BOM (clarification_needed=False)."""
    state["clarification_needed"] = False
    state["clarification_questions"] = []
    state["clarification_context"] = {}


def _consolidate_user_input(state: AgenticSystemState, merged: str) -> int:
    """Hand the full accumulated requirement downstream (solution memory and the
    final response reflect the consolidated requirement, not 'yes go ahead').
    Returns the consolidated length (0 if nothing was replaced)."""
    if merged and merged != state.get("user_input", ""):
        state["workflow_data"]["original_user_input"] = state.get("user_input", "")
        state["user_input"] = merged
        logging.info(f"[HOLISTIC] Consolidated requirement handed downstream ({len(merged)} chars).")
        return len(merged)
    return 0


def _trace_outcome(session_id: str, outcome: str, node_start: float, **extra) -> None:
    """Emit one structured outcome record per gate turn (latency + verdict path)."""
    _trace_identification("holistic_outcome", {
        "session_id": session_id,
        "outcome": outcome,
        "node_duration_ms": round((time.perf_counter() - node_start) * 1000),
        **extra,
    })


def _run_refinement_turn(
    state: AgenticSystemState, session_id: str, ctx: dict, user_input: str,
    conversation_context: str, node_start: float,
) -> AgenticSystemState:
    """Post-build refinement: the user supplies additional/changed requirements
    after proceeding with known gaps. One REFINEMENT-mode LLM call re-scores
    completeness (informational — never blocks) and updates the existing BOM;
    the Python merge safety-net enforces preservation and computes the
    per-item _needs_deep_analysis flags that let expansion/infer skip
    untouched items. Deliberately unchunked: the update must see the whole
    merged requirement + existing BOM in one view."""
    state["awaiting_holistic_confirmation"] = False
    state["workflow_data"]["awaiting_holistic_confirmation"] = False

    user_id = state.get("user_id")
    merged = _build_merged_requirement(ctx, user_input) or user_input
    existing_instruments = _snake_keys_deep(state.get("instruments") or [])
    existing_accessories = _snake_keys_deep(state.get("accessories") or [])
    bom_json = _strip_bom_for_prompt(existing_instruments, existing_accessories)

    parsed = _run_combined_llm(
        state, merged, "REFINEMENT", list(ctx.get("asked_questions") or []),
        conversation_context, existing_bom=bom_json,
    )

    upd_instruments, i_changed, i_new = _merge_refinement(
        existing_instruments, parsed.get("instruments") or [], "product_name", user_input)
    upd_accessories, a_changed, a_new = _merge_refinement(
        existing_accessories, parsed.get("accessories") or [], "accessory_name", user_input)

    extraction = {
        "project_name": parsed.get("project_name") or "",
        "sub_systems": parsed.get("sub_systems", []) or [],
        "instruments": upd_instruments,
        "accessories": upd_accessories,
        "summary": parsed.get("summary") or "Requirements refined.",
    }
    _apply_extraction(state, extraction, conversation_context)
    _consolidate_user_input(state, merged)
    _clear_clarification(state)
    state["workflow_data"]["holistic_complete"] = True
    state["workflow_data"]["refinement_applied"] = True

    remaining = [m for m in (parsed.get("critical_missing") or [])
                 if str(m.get("severity", "")).lower() == "critical"]
    scores = parsed.get("engineering_completeness") or {}
    state["workflow_data"]["engineering_completeness"] = {**scores, "remaining_gaps": remaining}

    # Keep the refinement window open while criticals remain; close it once
    # the requirement is complete.
    if remaining:
        store_holistic_context(session_id, {
            "stage": "proceeded_with_gaps",
            "original_requirement": merged,
            "accumulated_inputs": [],
            "asked_questions": list(ctx.get("asked_questions") or []),
            "gaps": remaining,
            "ask_count": int(ctx.get("ask_count") or 1),
        }, user_id=user_id)
    else:
        clear_holistic_context(session_id, user_id=user_id)

    changed = i_changed + a_changed
    new = i_new + a_new
    unchanged = len(upd_instruments) + len(upd_accessories) - changed - new
    logging.info(f"[HOLISTIC] Refinement applied: {changed} changed, {new} new, "
                 f"{unchanged} unchanged item(s); {len(remaining)} critical gap(s) remain.")
    _trace_outcome(session_id, "refined", node_start,
                   changed=changed, new=new, unchanged=unchanged,
                   overall_score=scores.get("overall_score"),
                   remaining_criticals=len(remaining))
    return state


def _gap_progress_info(parsed: dict, ctx: dict, verdict: dict) -> tuple[bool, list[str]]:
    """Did this follow-up turn RESOLVE any of the previously asked gaps?

    Primary signal: the LLM's per-question gap_resolution statuses. Fallback for
    models that omit the field: the remaining-criticals list shrank versus what
    the memory context remembered. Returns (progress, resolved_topic_labels)."""
    gap_res = parsed.get("gap_resolution") or []
    resolved_topics = [
        (g.get("topic") or g.get("question") or "").strip()
        for g in gap_res
        if str(g.get("status", "")).lower() in ("resolved", "partial") and isinstance(g, dict)
    ]
    resolved_topics = [t for t in resolved_topics if t]
    progress = bool(resolved_topics)
    if not progress and not gap_res:
        # Field omitted — infer progress from the criticals delta.
        progress = len(verdict.get("gaps") or []) < len(ctx.get("gaps") or [])
    return progress, resolved_topics


def _on_analysis_failed(state: dict, exc: BaseException) -> dict:
    """Exhausted-retries hook: without an extraction there is no downstream BOM,
    so the turn must surface an error (no proceed-anyway degradation)."""
    if isinstance(state, dict):
        state.setdefault("warnings", []).append(f"Requirement analysis failed: {exc}")
        state.setdefault("agent_path", []).append("solution_workflow.holistic_agent.failed")
        state["error"] = f"Failed to analyze requirements: {exc}"
    logging.error(f"[HOLISTIC] Analysis failed after retries: {exc}")
    return state


@retryable_node(
    max_attempts=2,
    label="holistic_agent",
    on_exhausted=_on_analysis_failed,
)
def holistic_agent_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Turn semantics (memory-backed via get/store/clear_holistic_context;
    one combined LLM call per turn):
      Turn 1, short/mid input: combined call (gate ENABLED). Holistic -> extraction
        written to deep_analysis in the same call. Gapped -> full question list,
        reason="holistic_gap", store context (stage="awaiting_gap_answers").
      Turn 1, long input (> chunk threshold): gate BYPASSED, chunked-parallel
        extraction exactly as the old analyze_query.
      Follow-up (awaiting -- flag OR server-side stage):
        - Affirmative reply -> extract the consolidated requirement (BYPASSED),
          open the refinement window, proceed.
        - Non-affirmative reply -> combined call on the MERGED requirement
          (ENABLED, previously-asked questions passed), then a THREE-WAY
          decision on the result:
            * holistic -> extraction already in the same response; proceed.
            * still gapped WITH resolution progress (the reply answered some
              asked questions -- see _gap_progress_info) -> "gap_progress":
              acknowledgment of what was received + ONLY the residual
              questions (re-asking residuals allowed), stage stays
              awaiting_gap_answers, memory gaps shrink to the residuals.
            * still gapped with NO progress (ambiguous/stalling reply) ->
              "Shall I proceed?" confirmation (reason="holistic_confirm"),
              re-asked on further ambiguous turns.
    """
    node_start = time.perf_counter()
    state.setdefault("agent_path", []).append("solution_workflow.holistic_agent")
    state.setdefault("workflow_data", {})

    session_id = state.get("session_id", "default")
    user_id = state.get("user_id")
    user_input = state.get("user_input", "")
    ctx = get_holistic_context(session_id, user_id=user_id)
    # Server-side stage is authoritative; the frontend-echoed flag is a fallback
    # so the flow survives even if the round-trip or the memory store fails.
    flag_awaiting = state.get("workflow_data", {}).get("awaiting_holistic_confirmation", False)
    awaiting = bool(ctx.get("stage")) or flag_awaiting

    _trace_identification("holistic_start", {
        "session_id": session_id,
        "awaiting": awaiting,
        "awaiting_source": "memory" if ctx.get("stage") else ("flag" if flag_awaiting else "none"),
        "stage": ctx.get("stage"),
        "ask_count": ctx.get("ask_count", 0),
        "input_chars": len(user_input or ""),
    })

    if not user_input or not user_input.strip():
        state["error"] = "Empty requirement input"
        _trace_outcome(session_id, "empty_input", node_start)
        return state

    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "holistic_analysis",
            "message": "Analyzing Requirements",
            "progress": 15,
        })

    conversation_context = _build_conversation_context(state)

    # ------------------------------------------------------------------
    # REFINEMENT WINDOW -- the user proceeded with known gaps and a solution
    # was built; every follow-up now incrementally refines it (checked BEFORE
    # the awaiting branch: this stage also makes `awaiting` truthy).
    # ------------------------------------------------------------------
    if ctx.get("stage") == "proceeded_with_gaps":
        return _run_refinement_turn(state, session_id, ctx, user_input, conversation_context, node_start)

    # ------------------------------------------------------------------
    # FOLLOW-UP TURN HANDLING -- checked BEFORE assuming a fresh gate run.
    # ------------------------------------------------------------------
    if awaiting:
        state["awaiting_holistic_confirmation"] = False
        state["workflow_data"]["awaiting_holistic_confirmation"] = False

        if not state.get("pid_project_type"):
            from domain.solution.services.pid_builder_service import parse_pid_clarification_response
            if any(k in user_input.lower() for k in ["greenfield", "brownfield", "clean-sheet", "scratch", "new plant", "retrofit", "existing", "drawing", "image"]):
                state["pid_project_type"] = parse_pid_clarification_response(user_input)
                logging.info(f"[HOLISTIC] Extracted P&ID project type from user response: {state['pid_project_type'].upper()}")

        if _is_affirmative(user_input):
            logging.info("[HOLISTIC] User confirmed proceeding -- extracting consolidated requirement (gate bypassed).")
            merged = _build_merged_requirement(ctx) or user_input
            extraction = _extract_bypassed(state, merged, conversation_context)
            consolidated_chars = _consolidate_user_input(state, merged)
            _apply_extraction(state, extraction, conversation_context)
            _clear_clarification(state)
            state["workflow_data"]["holistic_gate_bypassed"] = True
            # Open the REFINEMENT WINDOW instead of clearing: the known gaps are
            # kept so later follow-ups (e.g. the user supplies the missing data
            # after studying the built design) incrementally refine the solution
            # rather than regenerating it or falling into the modification path.
            store_holistic_context(session_id, {
                "stage": "proceeded_with_gaps",
                "original_requirement": merged,
                "accumulated_inputs": [],
                "asked_questions": list(ctx.get("asked_questions") or []),
                "gaps": list(ctx.get("gaps") or []),
                "ask_count": int(ctx.get("ask_count") or 1),
            }, user_id=user_id)
            _trace_outcome(session_id, "bypassed_confirmed", node_start,
                           ask_count=ctx.get("ask_count", 0), consolidated_chars=consolidated_chars,
                           instruments=len(extraction.get("instruments", [])),
                           refinement_window_opened=True)
            return state

        merged = _build_merged_requirement(ctx, user_input) or user_input
        asked_before = list(ctx.get("asked_questions") or [])

        # A merged requirement past the chunk threshold takes the long-input
        # path: gate bypassed, chunked extraction (the user has already answered
        # once and supplied substantial detail).
        if len(merged) > _CHUNK_THRESHOLD_CHARS:
            logging.info("[HOLISTIC] Merged requirement exceeds chunk threshold -- extracting (gate bypassed).")
            extraction = _extract_bypassed(state, merged, conversation_context)
            consolidated_chars = _consolidate_user_input(state, merged)
            _apply_extraction(state, extraction, conversation_context)
            _clear_clarification(state)
            state["workflow_data"]["holistic_complete"] = True
            clear_holistic_context(session_id, user_id=user_id)
            _trace_outcome(session_id, "holistic_after_followup", node_start,
                           ask_count=ctx.get("ask_count", 0), consolidated_chars=consolidated_chars,
                           gate_bypassed_long=True, instruments=len(extraction.get("instruments", [])))
            return state

        logging.info("[HOLISTIC] Re-running combined gate+extraction on merged requirement.")
        parsed = _run_combined_llm(state, merged, "ENABLED", asked_before, conversation_context)
        verdict = _normalize_verdict(parsed, "ENABLED", asked_before)

        if verdict["is_holistic"]:
            extraction = _merge_extraction_results([parsed])
            consolidated_chars = _consolidate_user_input(state, merged)
            _apply_extraction(state, extraction, conversation_context)
            _clear_clarification(state)
            state["workflow_data"]["holistic_complete"] = True
            clear_holistic_context(session_id, user_id=user_id)
            _trace_outcome(session_id, "holistic_after_followup", node_start,
                           ask_count=ctx.get("ask_count", 0), consolidated_chars=consolidated_chars,
                           instruments=len(extraction.get("instruments", [])))
            return state

        # Still gapped -- three-way decision based on RESOLUTION PROGRESS:
        # the user actively answering questions gets an acknowledgment + only
        # the residual questions; the bare confirm prompt is reserved for
        # ambiguous/no-progress replies (the anti-loop case).
        asked_union = asked_before + [q for q in verdict["questions"] if q not in asked_before]
        progress, resolved_topics = _gap_progress_info(parsed, ctx, verdict)
        next_ask = int(ctx.get("ask_count") or 1) + 1

        # Convergence cap: the gate gets at most _MAX_GATE_ASKS question rounds.
        # Beyond that, auto-proceed — build from the consolidated requirement and
        # hand the remaining gaps to the refinement window, which exists exactly
        # for post-build gap filling. Prevents perfectionism loops.
        if next_ask > _MAX_GATE_ASKS:
            logging.info(f"[HOLISTIC] Ask-round cap reached ({_MAX_GATE_ASKS}) -- auto-proceeding "
                         f"with {len(verdict['gaps'])} remaining gap(s).")
            extraction = _extract_bypassed(state, merged, conversation_context)
            consolidated_chars = _consolidate_user_input(state, merged)
            _apply_extraction(state, extraction, conversation_context)
            _clear_clarification(state)
            state["workflow_data"]["holistic_gate_bypassed"] = True
            remaining_cats = sorted({str(g.get("category", "")) for g in verdict["gaps"] if g.get("category")})
            if remaining_cats:
                state.setdefault("warnings", []).append(
                    f"Proceeded after {_MAX_GATE_ASKS} clarification rounds; remaining gaps: "
                    f"{', '.join(remaining_cats)} — supply them anytime to refine the solution.")
            store_holistic_context(session_id, {
                "stage": "proceeded_with_gaps",
                "original_requirement": merged,
                "accumulated_inputs": [],
                "asked_questions": asked_union,
                "gaps": verdict["gaps"],
                "ask_count": next_ask,
            }, user_id=user_id)
            _trace_outcome(session_id, "auto_proceed_max_asks", node_start,
                           ask_count=next_ask, remaining_criticals=len(verdict["gaps"]),
                           consolidated_chars=consolidated_chars,
                           instruments=len(extraction.get("instruments", [])))
            return state

        if progress and verdict["questions"]:
            logging.info(f"[HOLISTIC] Gap progress: {len(resolved_topics)} item(s) resolved, "
                         f"{len(verdict['questions'])} residual question(s) remain.")
            store_holistic_context(session_id, {
                "stage": "awaiting_gap_answers",
                "original_requirement": ctx.get("original_requirement") or user_input,
                "accumulated_inputs": list(ctx.get("accumulated_inputs") or []) + [user_input],
                "asked_questions": asked_union,
                "gaps": verdict["gaps"],
                "ask_count": int(ctx.get("ask_count") or 1) + 1,
            }, user_id=user_id)
            state["clarification_needed"] = True
            state["clarification_questions"] = verdict["questions"]
            state["clarification_context"] = {
                "reason": "holistic_gap",
                "gaps": verdict["gaps"],
                "reasoning": verdict["reasoning"],
                "engineering_completeness": verdict["scores"],
                "resolved_topics": resolved_topics,
            }
            received = ", ".join(resolved_topics) if resolved_topics else "your additional details"
            residual_list = "\n".join(f"- {q}" for q in verdict["questions"])
            state["workflow_data"]["response_message"] = (
                f"Received and incorporated: {received}. "
                "Still missing the following — answer them, or say 'go ahead' to proceed without:\n\n"
                + residual_list
            )
            state["workflow_data"]["response_type"] = "clarification"
            state["awaiting_holistic_confirmation"] = True
            state["workflow_data"]["awaiting_holistic_confirmation"] = True
            _trace_outcome(session_id, "gap_progress", node_start,
                           resolved=len(resolved_topics),
                           remaining_questions=len(verdict["questions"]),
                           remaining_criticals=len(verdict["gaps"]),
                           overall_score=(verdict["scores"] or {}).get("overall_score"))
            return state

        logging.info("[HOLISTIC] Still gapped after follow-up (no resolution progress) -- asking proceed confirmation.")
        store_holistic_context(session_id, {
            "stage": "awaiting_proceed_confirm",
            "original_requirement": ctx.get("original_requirement") or user_input,
            "accumulated_inputs": list(ctx.get("accumulated_inputs") or []) + [user_input],
            "asked_questions": asked_union,
            "gaps": verdict["gaps"],
            "ask_count": int(ctx.get("ask_count") or 1) + 1,
        }, user_id=user_id)
        state["clarification_needed"] = True
        state["clarification_questions"] = []
        state["clarification_context"] = {
            "reason": "holistic_confirm",
            "gaps": verdict["gaps"],
            "reasoning": verdict["reasoning"],
            "engineering_completeness": verdict["scores"],
        }
        state["workflow_data"]["response_message"] = _CONFIRM_MESSAGE
        state["workflow_data"]["response_type"] = "clarification"
        state["awaiting_holistic_confirmation"] = True
        state["workflow_data"]["awaiting_holistic_confirmation"] = True
        _trace_outcome(session_id, "confirm_prompt", node_start,
                       re_ask=ctx.get("stage") == "awaiting_proceed_confirm",
                       ask_count=int(ctx.get("ask_count") or 1) + 1,
                       new_questions=len([q for q in verdict["questions"] if q not in asked_before]))
        return state

    # ------------------------------------------------------------------
    # FIRST-TIME PATH (not awaiting).
    # ------------------------------------------------------------------
    if len(user_input) > _CHUNK_THRESHOLD_CHARS:
        logging.info("[HOLISTIC] Long input -- gate bypassed, chunked extraction.")
        extraction = _extract_bypassed(state, user_input, conversation_context)
        _apply_extraction(state, extraction, conversation_context)
        _clear_clarification(state)
        state["workflow_data"]["holistic_complete"] = True
        _trace_outcome(session_id, "holistic_first_pass", node_start, gate_bypassed_long=True,
                       instruments=len(extraction.get("instruments", [])))
        return state

    parsed = _run_combined_llm(state, user_input, "ENABLED", [], conversation_context)
    verdict = _normalize_verdict(parsed, "ENABLED", [])

    # Blocked verdict with an empty "questions" array: the LLM under-populated
    # questions while still flagging concrete gaps. NEVER silently proceed to
    # extraction while real gaps exist -- synthesize grounded questions from
    # the gaps themselves instead. Only a TRULY non-informative response
    # (blocked, no questions, AND no gaps) falls through to extraction.
    if not verdict["is_holistic"] and len(verdict["questions"]) == 0:
        if verdict["gaps"]:
            synthesized = _synthesize_questions_from_gaps(verdict["gaps"])
            logging.info(f"[HOLISTIC] Blocked verdict with no questions but {len(verdict['gaps'])} "
                         f"gap(s) -- synthesizing {len(synthesized)} question(s) instead of proceeding.")
            store_holistic_context(session_id, {
                "stage": "awaiting_gap_answers",
                "original_requirement": user_input,
                "accumulated_inputs": [],
                "asked_questions": synthesized,
                "gaps": verdict["gaps"],
                "ask_count": 1,
            }, user_id=user_id)
            state["clarification_needed"] = True
            state["clarification_questions"] = synthesized
            state["clarification_context"] = {
                "reason": "holistic_gap",
                "gaps": verdict["gaps"],
                "reasoning": verdict["reasoning"],
                "engineering_completeness": verdict["scores"],
            }
            state["workflow_data"]["holistic_complete"] = False
            synthesized_list = "\n".join(f"- {q}" for q in synthesized)
            state["workflow_data"]["response_message"] = (
                "Before I design the solution, I need a bit more information to make sure "
                "nothing critical is missing:\n\n" + synthesized_list
            )
            state["workflow_data"]["response_type"] = "clarification"
            state["awaiting_holistic_confirmation"] = True
            state["workflow_data"]["awaiting_holistic_confirmation"] = True
            _trace_outcome(session_id, "gap_questions", node_start,
                           questions_count=len(synthesized), gaps_count=len(verdict["gaps"]),
                           synthesized=True, overall_score=(verdict["scores"] or {}).get("overall_score"))
            return state

        logging.info("[HOLISTIC] Blocked verdict with no questions AND no gaps -- non-informative response, falling back to extraction.")
        if parsed.get("instruments"):
            extraction = _merge_extraction_results([parsed])
        else:
            extraction = _extract_bypassed(state, user_input, conversation_context)
        _apply_extraction(state, extraction, conversation_context)
        _clear_clarification(state)
        state["workflow_data"]["holistic_complete"] = True
        _trace_outcome(session_id, "holistic_first_pass", node_start, clamped_fallback=True,
                       overall_score=(verdict["scores"] or {}).get("overall_score"),
                       instruments=len(extraction.get("instruments", [])))
        return state

    if verdict["is_holistic"]:
        logging.info("[HOLISTIC] Requirement judged holistic -- extraction completed in the same call.")
        extraction = _merge_extraction_results([parsed])
        _apply_extraction(state, extraction, conversation_context)
        _clear_clarification(state)
        state["workflow_data"]["holistic_complete"] = True
        _trace_outcome(session_id, "holistic_first_pass", node_start,
                       instruments=len(extraction.get("instruments", [])))
        return state

    # If project scope is ambiguous, append P&ID scope question to holistic questions
    from domain.solution.services.pid_builder_service import should_request_pid_clarification, parse_pid_clarification_response
    has_active = bool(state.get("active_pid_graph") or state.get("pid_graph"))
    if should_request_pid_clarification(user_input, has_active_pid=has_active):
        pid_q = (
            "Plant / P&ID Scope: Is this a brand-new clean-sheet design from scratch (Greenfield) or a retrofit onto an existing plant / P&ID drawing (Brownfield)? "
            "If Brownfield, please provide details of your existing P&ID image/drawing, line numbers, or existing equipment tags to tie into."
        )
        if not any("greenfield" in q.lower() or "brownfield" in q.lower() for q in verdict["questions"]):
            verdict["questions"].append(pid_q)

    logging.info(f"[HOLISTIC] Gaps found -- asking {len(verdict['questions'])} grounded question(s).")
    store_holistic_context(session_id, {
        "stage": "awaiting_gap_answers",
        "original_requirement": user_input,
        "accumulated_inputs": [],
        "asked_questions": verdict["questions"],
        "gaps": verdict["gaps"],
        "ask_count": 1,
    }, user_id=user_id)
    state["clarification_needed"] = True
    state["clarification_questions"] = verdict["questions"]
    state["clarification_context"] = {
        "reason": "holistic_gap",
        "gaps": verdict["gaps"],
        "reasoning": verdict["reasoning"],
        "engineering_completeness": verdict["scores"],
    }
    state["workflow_data"]["holistic_complete"] = False
    questions_list = "\n".join(f"- {q}" for q in verdict["questions"])
    state["workflow_data"]["response_message"] = (
        "Before I design the solution, I need a bit more information to make sure "
        "nothing critical is missing:\n\n" + questions_list
    )
    state["workflow_data"]["response_type"] = "clarification"
    state["awaiting_holistic_confirmation"] = True
    state["workflow_data"]["awaiting_holistic_confirmation"] = True
    _trace_outcome(session_id, "gap_questions", node_start,
                   questions_count=len(verdict["questions"]),
                   gaps_count=len(verdict["gaps"]),
                   overall_score=(verdict["scores"] or {}).get("overall_score"))
    return state

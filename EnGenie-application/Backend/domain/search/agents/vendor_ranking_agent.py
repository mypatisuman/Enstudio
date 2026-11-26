"""
Node 6 — Vendor Ranking Agent (Flash with Reasoning)

Ranks all identified models using LLM-based evaluation.
Provides scores, strengths, and concerns for each product.
"""

import json
import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from domain.orchestrator.state import AgenticSystemState
from common.helpers.progress_tracker import progress_tracker
from common.helpers.node_retry import retryable_node
from common.ai.llm import get_flash_llm

logger = logging.getLogger(__name__)

_llm_flash = get_flash_llm(temperature=0.1)


def _build_comparison_table(vendor_matches: list[dict], spec_keys: list[str]) -> dict[str, Any]:
    """Pivot per-vendor spec_values (from vendor_analysis_agent) into a vendor x spec
    matrix — one row per analyzed product, aligned to the same ordered spec_keys."""
    if not spec_keys or not vendor_matches:
        return {"spec_keys": spec_keys, "rows": []}

    rows = []
    for match in vendor_matches:
        if not isinstance(match, dict):
            continue
        spec_values = match.get("spec_values") or {}
        rows.append({
            "vendor": match.get("vendor", ""),
            "product_name": match.get("product_name", ""),
            "model_family": match.get("model_family", ""),
            "values": {key: spec_values.get(key) for key in spec_keys},
        })
    return {"spec_keys": spec_keys, "rows": rows}


def _degrade_ranking(state: AgenticSystemState, exc: BaseException) -> AgenticSystemState:
    """Graceful degradation for ranking: once retries are exhausted (or on a
    non-transient failure), keep whatever ranking vendor analysis already produced
    (rather than blanking it) and continue with a warning."""
    logger.error(f"[VENDOR_RANKING] Ranking degraded after retries: {exc}")
    state["error_message"] = f"Ranking failed: {exc}"
    existing = state.get("ranked_products") or []
    state["overall_ranking"] = state.get("overall_ranking") or {"ranked_products": existing}
    if not state.get("comparison_table"):
        state["comparison_table"] = _build_comparison_table(
            state.get("vendor_matches") or [], state.get("comparison_spec_keys") or []
        )
    state.setdefault("warnings", []).append(
        "Final ranking step was skipped after retries; showing matched products without re-ranking."
    )
    return state


@retryable_node(max_attempts=2, label="vendor_ranking_agent", on_exhausted=_degrade_ranking)
def vendor_ranking_agent(state: AgenticSystemState) -> AgenticSystemState:
    """
    Vendor Ranking Agent — Flash with Reasoning (Node 6).

    Ranks all identified product models using Flash LLM.
    Generates scores, strengths, and concerns for each product.
    """
    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "vendor_ranking",
            "message": "Ranking Models",
            "progress": 90,
        })

    import threading as _threading
    logger.info(
        f"[VENDOR_RANKING] ENTER — "
        f"session_id={state.get('session_id')!r} "
        f"stream_id={stream_id!r} "
        f"thread={_threading.current_thread().name} "
        f"active_threads={_threading.active_count()} "
        f"vendor_matches_in_state={len(state.get('vendor_matches', []))} "
        f"ranked_products_in_state={len(state.get('ranked_products', []))}"
    )
    logger.info("[VENDOR_RANKING] Node 6: Vendor Ranking Agent (Flash)")

    try:
        from domain.search.agents.search_agent import _load_prompt
        from domain.search.agents.vendor_analysis_agent import _safe_json_parser

        # Get vendor matches directly from state
        vendor_matches = state.get("vendor_matches", [])
        structured_requirements = state.get("structured_requirements", "")

        if not vendor_matches:
            logger.warning(
                f"[VENDOR_RANKING] No vendor matches to rank — "
                f"session_id={state.get('session_id')!r} "
                f"product_type={state.get('detected_product_type')!r} "
                f"deep_analysis_complete={state.get('deep_analysis_complete')} "
                f"error_message={state.get('error_message')!r}. "
                f"Likely cause: vendor analysis produced 0 matches or failed silently."
            )
            state["ranked_products"] = []
            state["overall_ranking"] = {"ranked_products": []}
            state["comparison_table"] = {"spec_keys": state.get("comparison_spec_keys") or [], "rows": []}
            return state

        logger.info(f"[VENDOR_RANKING] Ranking {len(vendor_matches)} models")

        prompt_content = _load_prompt('ranking_prompt.md')
        ranking_prompt = ChatPromptTemplate.from_template(prompt_content)
        FORMAT_INSTRUCTIONS_RANKING = """
Return ONLY a valid JSON array matching the following schema, with no markdown formatting or code fences. If there are no matches, return an empty array [].
[
  {
    "rank": 1,
    "product_name": "exact model name",
    "vendor": "vendor name",
    "model_family": "product family",
    "overall_score": 85,
    "requirements_match": true,
    "key_strengths": "Detailed markdown list of strengths as per Guidelines",
    "concerns": "Detailed markdown list of concerns as per Guidelines"
  }
]
"""

        ranking_chain = ranking_prompt.partial(format_instructions=FORMAT_INSTRUCTIONS_RANKING) | _llm_flash | _safe_json_parser()

        ranked_products = ranking_chain.invoke({
            "structured_requirements": structured_requirements,
            "vendor_analysis": json.dumps(vendor_matches, indent=2)
        })

        if isinstance(ranked_products, dict) and "ranked_products" in ranked_products:
             ranked_products = ranked_products["ranked_products"]

        if not isinstance(ranked_products, list):
            ranked_products = []

        logger.info(
            f"[VENDOR_RANKING] EXIT — ranked={len(ranked_products)} from {len(vendor_matches)} raw matches "
            f"session_id={state.get('session_id')!r} "
            f"thread={_threading.current_thread().name}"
        )

        # Store results in state
        state["ranked_products"] = ranked_products
        state["overall_ranking"] = {"ranked_products": ranked_products}

        comparison_spec_keys = state.get("comparison_spec_keys") or []
        state["comparison_table"] = _build_comparison_table(vendor_matches, comparison_spec_keys)

        state["agent_path"].append("vendor_ranking_agent")

    except Exception as e:
        # Re-raise so @retryable_node retries transient failures; persistent ones
        # fall through to _degrade_ranking (preserves analysis ranking + warns).
        logger.exception(f"[VENDOR_RANKING] Ranking failed: {e}")
        raise

    return state

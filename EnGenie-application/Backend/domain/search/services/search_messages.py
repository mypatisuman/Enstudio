"""
Generate user-facing chat messages for the unified sidebar-first search flow.

Uses SEARCH_ALL_SPECS_COMBINED_PROMPT / SEARCH_ALL_SPECS_UPDATE_PROMPT so the
API, LangGraph workflow, and agents share one messaging model (no HITL prompts).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def generate_sidebar_specs_message(
    product_type: str,
    session_id: str | None = None,
    *,
    is_modification: bool = False,
    max_turns: int = 4,
) -> str:
    """LLM-generated sidebar-first message after spec extraction or update."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from common.ai.llm import get_flash_llm
    from common.ai.memory import format_conversation_for_prompt
    from common.ai.prompts.response import (
        SEARCH_ALL_SPECS_COMBINED_PROMPT,
        SEARCH_ALL_SPECS_UPDATE_PROMPT,
    )

    pt = (product_type or "product").strip() or "product"
    raw = format_conversation_for_prompt(session_id, max_turns=max_turns) if session_id else ""
    ctx = raw.replace("{", "{{").replace("}", "}}") if (raw and raw != "No previous conversation.") else "No prior conversation."

    template = SEARCH_ALL_SPECS_UPDATE_PROMPT if is_modification else SEARCH_ALL_SPECS_COMBINED_PROMPT
    fallback = (
        f"I've updated your **{pt}** specifications in the left panel. Review them there, fill any gaps, or type **proceed** to run the search."
        if is_modification
        else f"I've loaded **{pt}** specifications, standards, and advanced options in the left panel. Review them there, fill any gaps, or type **proceed** to run the search."
    )

    try:
        chain = ChatPromptTemplate.from_template(template) | get_flash_llm(temperature=0.1) | StrOutputParser()
        return chain.invoke({"product_type": pt, "conversation_context": ctx}).strip() or fallback
    except Exception as exc:
        logger.warning("[SEARCH_MESSAGES] Sidebar message generation failed: %s", exc)
        return fallback

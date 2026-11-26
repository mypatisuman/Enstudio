"""A one-shot grounded answer: retrieve the drawing's cards, ask the LLM once,
check the citations. For drawings that are not in a Describe chat (a
solution-session PIDGraph); the Describe chat answers through its Query agent,
which can also call the exact graph tools.
"""
from __future__ import annotations

import logging

from domain.pid_rag.citations import check_citations
from domain.pid_rag.retriever import retrieve

logger = logging.getLogger(__name__)


def _complete(prompt: str) -> str:
    """Module-level for testability."""
    from adapters.llm_factory import get_provider
    return get_provider().complete(prompt, max_tokens=900, tier="smart").text or ""


def answer_question(key: str, question: str, *, snapshot: dict | None = None,
                    memory_context: str = "") -> dict:
    """{"reply", "citations", "sources", "unknown"} for a question about the drawing
    indexed under `key` (a studio.db project id, or "session:<id>" for a PIDGraph)."""
    from agents.describe.prompts.catalog import DESCRIBE_RAG_ANSWER_V1
    from agents.prompts import fill_prompt
    found = retrieve(key, question, snapshot=snapshot)
    if not found["chunks"]:
        return {"reply": "This project has no P&ID yet, so there is nothing to answer from.",
                "citations": [], "sources": [], "unknown": []}
    prompt = fill_prompt(DESCRIBE_RAG_ANSWER_V1, {
        "question": question, "context": found["context"],
        "memory": memory_context or "(none)"})
    try:
        raw = _complete(prompt).strip()
    except Exception as exc:
        logger.warning("[pid_rag] answer call failed: %s", exc)
        return {"reply": "I could not reach the language model - please try again.",
                "citations": [], "sources": [c["id"] for c in found["chunks"]], "unknown": []}
    from domain.pid_rag.snapshot import load_snapshot
    tags = (snapshot or load_snapshot(key))["tags"]
    checked = check_citations(raw, tags)
    return {"reply": checked["reply"], "citations": checked["citations"],
            "sources": [c["id"] for c in found["chunks"]], "unknown": checked["unknown"]}

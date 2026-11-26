"""
Project service layer — app-level orchestration for project management.

Delegates to common/repositories/project_repository.py (MongoProjectManager).
Route handlers import from here to stay thin HTTP-only layers.
"""
from common.infra.repositories.project_repository import mongo_project_manager


def save_project(user_id: str, data: dict) -> dict:
    """Save or update a project. Returns saved project dict."""
    return mongo_project_manager.save_project(user_id, data)


def get_user_projects(user_id: str) -> list:
    """Return all active projects for a user (metadata only — no blob loading)."""
    return mongo_project_manager.get_user_projects(user_id)


def get_project_details(project_id: str, user_id: str) -> dict:
    """Return full project data, auto-migrating from GridFS to Azure Blob if needed."""
    return mongo_project_manager.get_project_details(project_id, user_id)


def delete_project(project_id: str, user_id: str) -> bool:
    """Permanently delete a project from MongoDB and Azure Blob Storage."""
    return mongo_project_manager.delete_project(project_id, user_id)


def _has_results(candidate: dict) -> bool:
    """Exclude only projects KNOWN to be empty. When the count fields are absent
    (legacy projects saved before counts existed), keep them — Open will load the
    blob and restore whatever instruments it holds."""
    ic, ac = candidate.get("instruments_count"), candidate.get("accessories_count")
    if ic is None and ac is None:
        return True
    return bool((ic or 0) or (ac or 0))


def match_saved_projects(user_id: str, session_id: str, query: str, threshold: float = 0.80, top_k: int = 25,
                         embed_text: str | None = None) -> dict:
    """
    Episodic recall — the CANONICAL semantic matcher (single source of truth for
    thresholds and filtering; used by the episodic_recall agent, the router
    classifier, and POST /api/projects/match).

    Check whether an incoming request semantically matches one of the user's saved
    projects. If so, remember the match against the session and return a message
    asking whether to retrieve it.

    Threshold: matching is against the project SIGNATURE (name + type +
    requirements + description) with cosine similarity rescaled to [0,1], so even
    an identical re-typed request tops out ~0.91 — 0.95 never matches. 0.80
    cleanly separates same-topic projects (>=0.85) from unrelated ones (<0.70).
    top_k is deliberately WIDE: near-duplicate empty projects can rank highest by
    similarity and would otherwise crowd out the substantive matches before the
    results-filter runs.

    embed_text: optional richer text to EMBED for the similarity search (e.g. the
    query enriched with session thread context by the episodic_recall agent).
    ``query`` stays the bookkeeping key — declined-check and the pending offer are
    stored against it so Ignore keeps matching what the user actually typed.

    Returns:
        {
          "matched": bool,
          "message": str,            # "shall I retrieve it?" prompt when matched
          "candidates": list[dict],  # substantive matches (highest similarity first)
        }
    """
    from common.ai.memory import (
        build_recall_prompt,
        clear_pending_recall,
        is_recall_declined,
        store_pending_recall,
    )

    if session_id and is_recall_declined(session_id, query):
        return {"matched": False, "message": "", "candidates": []}

    raw_candidates = mongo_project_manager.find_similar_projects(
        user_id, embed_text or query, threshold=threshold, top_k=top_k)
    candidates = [c for c in raw_candidates if _has_results(c)]

    if not candidates:
        # No substantive match — drop any stale offer.
        if session_id:
            clear_pending_recall(session_id)
        return {"matched": False, "message": "", "candidates": []}

    if session_id:
        store_pending_recall(session_id, query, candidates)

    return {
        "matched": True,
        "message": build_recall_prompt(candidates),
        "candidates": candidates,
    }


def decline_recall(session_id: str) -> dict:
    """
    Episodic recall — decline via Ignore button.

    Clears the pending offer, marks the original query as declined so a fresh
    re-run is not blocked by another recall prompt, and returns the original query.
    """
    from common.ai.memory import clear_pending_recall, get_pending_recall, mark_recall_declined

    pending = get_pending_recall(session_id) if session_id else {}
    original_query = (pending.get("query") or "").strip()

    if original_query and session_id:
        mark_recall_declined(session_id, original_query)
    if session_id:
        clear_pending_recall(session_id)

    return {
        "action": "decline",
        "original_query": original_query,
        "message": "Okay — I'll analyze your request from scratch.",
    }

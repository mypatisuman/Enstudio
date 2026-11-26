"""
Episodic Recall agent -- runs AFTER the holistic gate passes.

Position: project_intent -> holistic_agent -> episodic_recall ->
expansion. The saved-project offer only fires for COMPLETE requirements (the
gate's questions always come first), and matching runs on the CONSOLIDATED
requirement (original + gate answers) for better match quality. Continuation
turns (the user already answered gate questions or said "go ahead") skip the
offer entirely -- interrupting them with "you have a saved project" after they
invested in the flow would be hostile.

The recall QUERY is thread-aware: thin inputs ("same condenser setup but at
100 psi") are enriched with the session's own semantic context memory — the
latest gate-consolidated requirement, else recent substantive user turns —
before embedding, so a short in-thread re-request can still reach the saved
project it refers to. Pending/declined bookkeeping stays keyed on the RAW
input (what the user actually typed / what Ignore was clicked against).
Projects BORN from this session (episode-linked on save) are never offered
back to it (own-project guard).

Checks whether the request semantically matches one of the user's SUBSTANTIVE
saved projects (embedding cosine similarity via the canonical matcher in
app/services/project_service.py) and, on a match, offers to reopen it via the
frontend's "Repeated Request Detected" modal (Open / Preview / Ignore buttons)
INSTEAD of continuing to expansion. The offer's pending / declined bookkeeping
lives in common/ai/memory/episodic_recall.py; the modal's buttons resolve it
through dedicated endpoints (/api/projects/recall/ignore,
/api/projects/recall/dismiss, GET /api/projects/{id}) -- never through text.

On an embedding match, a Flash-LLM verification pass (prompt:
prompts/episodic_recall.md) judges each candidate same_project / modification /
different -- embeddings can't tell "same project re-typed" from "similar wording,
different process" -- and writes a natural offer message naming the best match.
The LLM runs ONLY on match-hit turns, is disabled via EPISODIC_RECALL_LLM_VERIFY=0,
and any LLM failure falls back to offering all embedding candidates with the
template message (never blocks, never loses an offer).

Recall is best-effort: any failure proceeds down the BOM pipeline
(expansion ∥ solution_build) and never blocks a solution run.
"""

import json
import logging
import os
import time
from datetime import datetime

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from domain.orchestrator.state import AgenticSystemState
from domain.solution.memory import append_node_execution_context
from domain.solution.agents.shared import _load_prompt, _parse_llm_json, _trace_identification, llm_flash
from common.ai.llm import SOLUTION_LLM_PROVIDER, with_json_mode
from common.ai.memory import (
    add_conversation_turn,
    clear_pending_recall,
    get_pending_recall,
    is_recall_declined,
    mark_recall_declined,
    store_pending_recall,
)
from common.helpers.node_retry import retryable_node

logger = logging.getLogger(__name__)

EPISODIC_RECALL_PROMPT = _load_prompt("episodic_recall.md")

# LLM match verification runs only on match-hit turns; kill-switch for ops.
_LLM_VERIFY_ENABLED = os.environ.get("EPISODIC_RECALL_LLM_VERIFY", "1") != "0"

# Query-side thread context: inputs shorter than this are enriched with the
# session's own semantic context before embedding (a thin re-request embeds
# too weakly to match the project it refers to); longer inputs already fill
# the embedder's ~256-token window on their own.
_ENRICH_INPUT_MAX_CHARS = int(os.environ.get("EPISODIC_RECALL_ENRICH_MAX_CHARS", "400"))
_RECALL_QUERY_BUDGET = 1200  # embedding model truncates at ~256 tokens


def _build_recall_query(session_id: str, user_input: str) -> tuple[str, bool]:
    """Compose the text EMBEDDED for recall matching: the current input first
    (so truncation keeps it), enriched with the session's thread context when
    the input alone is too thin — the latest gate-consolidated requirement,
    else the last substantive user turns. Returns (query_text, was_enriched).
    Best-effort: any lookup failure falls back to the raw input. Bookkeeping
    (pending offer / declined check) is NEVER keyed on the enriched text."""
    text = (user_input or "").strip()
    if not text or len(text) >= _ENRICH_INPUT_MAX_CHARS:
        return text, False

    context = ""
    try:
        from common.ai.memory import get_full_conversation_history, get_latest_consolidated_requirement
        context = (get_latest_consolidated_requirement(session_id) or "").strip()
        if not context:
            # No gate-consolidated requirement in this session yet — fall back
            # to the last substantive user turns (excluding the current one).
            prior: list[str] = []
            for turn in reversed(get_full_conversation_history(session_id)):
                if turn.get("role") != "user":
                    continue
                content = (turn.get("content") or "").strip()
                if not content or content == text or len(content) < 40:
                    continue
                prior.append(content)
                if len(prior) >= 2:
                    break
            context = "\n".join(reversed(prior))
    except Exception as exc:
        logging.warning(f"[EPISODIC_RECALL] Query enrichment failed (using raw input): {exc}")
        context = ""

    if not context:
        return text, False
    enriched = f"{text}\n\nEarlier context from this conversation:\n{context}"
    return enriched[:_RECALL_QUERY_BUDGET], True


def _verify_candidates_llm(
    state: AgenticSystemState, user_input: str, candidates: list[dict],
    related_episodes: list[dict] | None = None,
) -> tuple[list[dict], str]:
    """One Flash-LLM call classifying each embedding candidate as same_project /
    modification / different. Returns (verified candidates, offer message) --
    verified ordered strongest-first per the LLM, message "" when the model
    didn't produce one. Raises on LLM/parse failure so the caller can fall back
    to the unverified offer."""
    session_id = state.get("session_id", "default")

    candidate_payload = json.dumps([{
        "project_id": c.get("project_id"),
        "project_name": c.get("project_name"),
        "product_type": c.get("product_type"),
        "similarity": c.get("similarity"),
        "matched_on": c.get("matched_on"),
        "instruments_count": c.get("instruments_count"),
        "accessories_count": c.get("accessories_count"),
        "signature": c.get("input_signature_text") or "",
        "design_signature": c.get("design_signature_text") or "",
    } for c in candidates], indent=2)

    episodes_payload = "None"
    if related_episodes:
        episodes_payload = json.dumps([{
            "episode_text": e.get("episode_text"),
            "similarity": e.get("similarity"),
            "created_at": e.get("created_at"),
        } for e in related_episodes], indent=2)

    # Instructions go in the SYSTEM role, data in the HUMAN role. With the whole
    # template sent as a user message, Azure's prompt shield flagged the
    # identity/instruction text ("You are...") as a jailbreak attempt (400
    # content_filter) — instructions in the system role are exempt from that check.
    chain = (
        ChatPromptTemplate.from_messages([
            ("system", EPISODIC_RECALL_PROMPT),
            ("human",
             "**New Request:**\n{user_request}\n\n"
             "**Candidate Saved Projects:**\n{candidates}\n\n"
             "**Related Past Conversations:**\n{related_episodes}"),
        ])
        | with_json_mode(llm_flash, SOLUTION_LLM_PROVIDER)
        | StrOutputParser()
    )
    t_start = datetime.utcnow()
    raw = chain.invoke(
        {"user_request": user_input, "candidates": candidate_payload,
         "related_episodes": episodes_payload},
        config={"metadata": {"user_id": state.get("user_id"), "agent_type": "solution"}},
    )
    parsed = _parse_llm_json(raw)

    by_id = {c.get("project_id"): c for c in candidates}
    verified_ids = [pid for pid in (parsed.get("verified_project_ids") or []) if pid in by_id]
    verified = [by_id[pid] for pid in verified_ids]
    message = (parsed.get("offer_message") or "").strip()

    _trace_identification("episodic_recall_llm_verify", {
        "session_id": session_id,
        "duration_ms": round((datetime.utcnow() - t_start).total_seconds() * 1000),
        "in_count": len(candidates),
        "kept_count": len(verified),
        "verdicts": [
            {"project_id": cl.get("project_id"), "verdict": cl.get("verdict")}
            for cl in (parsed.get("classifications") or [])
        ],
    })
    return verified, message


def _public_candidates(candidates: list[dict]) -> list[dict]:
    """Strip the internal signature texts before candidates reach the pending
    store echo / frontend contract (matched_on is kept — additive and useful)."""
    _internal = ("input_signature_text", "design_signature_text")
    return [{k: v for k, v in c.items() if k not in _internal} for c in candidates]


def _trace_recall_outcome(session_id: str, outcome: str, node_start: float, **extra) -> None:
    _trace_identification("episodic_recall_outcome", {
        "session_id": session_id,
        "outcome": outcome,
        "node_duration_ms": round((time.perf_counter() - node_start) * 1000),
        **extra,
    })


def _on_recall_failed(state: dict, exc: BaseException) -> dict:
    """Recall is best-effort and must NEVER block a solution run: on exhausted
    retries just proceed down the BOM pipeline with no offer (matches the previous
    inline gate's try/except-and-continue behaviour; no user-visible warning)."""
    logging.warning(f"[EPISODIC_RECALL] Recall gate failed (continuing live): {exc}")
    if isinstance(state, dict):
        state.setdefault("workflow_data", {}).pop("recall_offer", None)
        _trace_identification("episodic_recall_outcome", {
            "session_id": state.get("session_id", "default"),
            "outcome": "failed",
            "error": str(exc)[:200],
        })
    return state


@retryable_node(max_attempts=2, label="episodic_recall", on_exhausted=_on_recall_failed)
def episodic_recall_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Post-gate node. Outcomes:
      offered           -- substantive saved-project match: recall_offer written to
                           workflow_data; routing short-circuits to final_response.
      declined_skip     -- user already clicked Ignore for this exact query.
      no_match          -- no substantive match; proceed to expansion ∥ solution_build.
      skipped_anonymous -- no user_id; recall only applies to signed-in users.
    """
    node_start = time.perf_counter()
    state.setdefault("agent_path", []).append("solution_workflow.episodic_recall")
    state.setdefault("workflow_data", {})

    session_id = state.get("session_id", "default")
    user_id = state.get("user_id")
    user_input = state.get("user_input", "")

    _trace_identification("episodic_recall_start", {
        "session_id": session_id,
        "user_id": user_id,
        "input_chars": len(user_input or ""),
    })

    if not user_id:
        _trace_recall_outcome(session_id, "skipped_anonymous", node_start)
        return state

    # Continuation guard: when the holistic gate consolidated a
    # multi-turn requirement (user answered gap questions or said "go ahead"),
    # the user has already invested in THIS run -- never interrupt it with a
    # saved-project offer.
    wd = state.get("workflow_data", {})
    if wd.get("original_user_input") or wd.get("holistic_gate_bypassed"):
        logging.info("[EPISODIC_RECALL] Continuation turn (gate answered/confirmed) — skipping recall offer.")
        _trace_recall_outcome(session_id, "skipped_continuation", node_start)
        return state

    # A typed message while an offer is pending = the user chose to move on
    # without the modal buttons. Treat it as an implicit decline of THAT offer
    # and run this turn fresh WITHOUT re-matching. Previously we cleared the
    # offer but re-ran the matcher in the same turn — with thread-context query
    # enrichment, "Ignore & run fresh" re-matched the same saved projects and
    # re-offered them immediately after the user explicitly ignored them.
    pending = get_pending_recall(session_id)
    if pending:
        pending_query = (pending.get("query") or "").strip()
        if pending_query:
            mark_recall_declined(session_id, pending_query)
        clear_pending_recall(session_id)
        logging.info("[EPISODIC_RECALL] Typed past pending offer — implicit decline, running fresh without re-offer")
        _trace_recall_outcome(session_id, "skipped_typed_past_offer", node_start)
        return state

    if is_recall_declined(session_id, user_input):
        logging.info(f"[EPISODIC_RECALL] Skipping recall offer — user declined for this query | user={user_id}")
        _trace_recall_outcome(session_id, "declined_skip", node_start)
        return state

    # Thread-context query: thin inputs are enriched with the session's own
    # semantic context so a short in-thread re-request can still reach its
    # saved project. Bookkeeping (pending/declined) stays on the raw input.
    recall_query, query_enriched = _build_recall_query(session_id, user_input)
    if query_enriched:
        logging.info(f"[EPISODIC_RECALL] Query enriched with session context "
                     f"({len(user_input)} -> {len(recall_query)} chars)")

    logging.info(f"[EPISODIC_RECALL] Checking saved-project recall | user={user_id} query='{user_input[:80]}'")
    # Canonical matcher: declined-check, wide-candidate fetch, substantive filter,
    # store_pending_recall and offer-message building all happen inside the service.
    from app.services.project_service import match_saved_projects
    match = match_saved_projects(str(user_id), session_id, user_input, embed_text=recall_query)

    candidates = match.get("candidates") or []

    # Own-project guard: never offer a conversation its own project back —
    # projects BORN from this session (episode-linked on save) are noise here.
    own_project_ids: set[str] = set()
    try:
        from common.ai.memory import get_session_project_ids
        own_project_ids = get_session_project_ids(session_id)
    except Exception as exc:
        logging.warning(f"[EPISODIC_RECALL] Own-project lookup failed (continuing): {exc}")
    own_filtered = 0
    if own_project_ids:
        kept = [c for c in candidates if str(c.get("project_id")) not in own_project_ids]
        own_filtered = len(candidates) - len(kept)
        if own_filtered:
            logging.info(f"[EPISODIC_RECALL] Filtered {own_filtered} own-session project(s) from the offer")
        candidates = kept

    # Conversation-episode recall: past MEANINGFUL exchanges matching this query.
    # Episodes linked to a saved project become full candidates (matched_on:
    # "conversation"); unlinked episodes inform the LLM verifier only.
    episodes: list[dict] = []
    try:
        from common.ai.memory import find_similar_episodes
        episodes = find_similar_episodes(str(user_id), recall_query)
    except Exception as exc:
        logging.warning(f"[EPISODIC_RECALL] Episode search failed (continuing): {exc}")
    linked_episodes = [e for e in episodes if e.get("project_id")]
    unlinked_episodes = [e for e in episodes if not e.get("project_id")]

    if linked_episodes:
        try:
            from common.infra.repositories.project_repository import mongo_project_manager
            from app.services.project_service import _has_results
            # own-session projects stay excluded (own-project guard above)
            known_ids = {c.get("project_id") for c in candidates} | own_project_ids
            for ep in linked_episodes:
                pid = str(ep.get("project_id"))
                if pid in known_ids:
                    continue
                cand = mongo_project_manager.build_candidate_from_project_id(
                    pid, str(user_id), ep.get("similarity") or 0.0)
                if cand and _has_results(cand):
                    candidates.append(cand)
                    known_ids.add(pid)
                    logging.info(f"[EPISODIC_RECALL] Episode match surfaced saved project "
                                 f"'{cand.get('project_name')}' (matched_on=conversation)")
        except Exception as exc:
            logging.warning(f"[EPISODIC_RECALL] Episode-candidate merge failed (continuing): {exc}")

    if not candidates:
        if own_filtered and match.get("candidates"):
            # The only match(es) were this session's own project — drop the
            # matcher's pending offer and proceed silently.
            clear_pending_recall(session_id)
        logging.info("[EPISODIC_RECALL] No substantive saved-project match — running solution agent fresh")
        _trace_recall_outcome(session_id, "no_match", node_start,
                              episodes_found=len(episodes), episodes_linked=len(linked_episodes),
                              own_filtered=own_filtered, query_enriched=query_enriched)
        return state

    # Episode matches may have extended — or the own-project guard shrunk —
    # the matcher's list: keep the pending offer in sync with what is offered.
    if len(candidates) != len(match.get("candidates") or []):
        store_pending_recall(session_id, user_input, candidates)

    # LLM match verification: embeddings pre-select, the LLM judges engineering
    # scope (same_project / modification / different). Best-effort — any failure
    # falls back to offering all embedding candidates with the template message.
    message = match.get("message") or ""
    if not message:
        # Candidates arrived purely via episode matches — build the template offer.
        from common.ai.memory import build_recall_prompt
        message = build_recall_prompt(candidates)
    llm_verified = False
    if _LLM_VERIFY_ENABLED:
        try:
            # The verifier sees the enriched query too — the session context
            # helps it judge scope, and the enrichment is labeled in the text.
            verified, llm_message = _verify_candidates_llm(
                state, recall_query, candidates, related_episodes=unlinked_episodes)
            if not verified:
                logging.info("[EPISODIC_RECALL] LLM verification rejected all embedding candidates — running fresh")
                clear_pending_recall(session_id)
                _trace_recall_outcome(session_id, "llm_rejected", node_start,
                                      candidates=len(candidates))
                return state
            if len(verified) != len(candidates):
                # Re-store the pending offer with only the verified subset so the
                # Ignore/Open flow operates on what was actually offered.
                store_pending_recall(session_id, user_input, verified)
            candidates = verified
            if llm_message:
                message = llm_message
            llm_verified = True
        except Exception as exc:
            logging.warning(f"[EPISODIC_RECALL] LLM verification failed — offering unverified match: {exc}")

    candidates = _public_candidates(candidates)
    add_conversation_turn(
        session_id=session_id, role="assistant", content=message,
        metadata={"cache_confirmation": True},
    )
    state["workflow_data"]["recall_offer"] = {
        "message": message,
        "matched_projects": candidates,
    }
    offered = ", ".join(f"{c.get('project_name')}({c.get('similarity')})" for c in candidates)
    logging.info(f"[EPISODIC_RECALL] RECALL OFFERED — Open/Preview/Ignore for: {offered}")
    _trace_recall_outcome(session_id, "offered", node_start,
                          candidates=len(candidates),
                          top_similarity=candidates[0].get("similarity"),
                          llm_verified=llm_verified,
                          episodes_found=len(episodes),
                          episodes_linked=len(linked_episodes),
                          query_enriched=query_enriched,
                          own_filtered=own_filtered)

    # Append to node-to-node context memory trail
    append_node_execution_context(
        state,
        "episodic_recall",
        f"Evaluated episodic recall: {len(candidates)} candidates offered" if candidates else "Evaluated episodic recall: proceeding with fresh engineering solution",
        {"candidates_count": len(candidates)},
    )
    return state


def route_after_episodic_recall(state: AgenticSystemState):
    """Short-circuit to final_response when a recall offer was made (the modal
    resolves it); otherwise fan out to the BOM pipeline AND the solution-build
    agent in parallel. solution_build runs ONLY here — after the gate confirmed
    the requirements are complete and no saved-project offer fired — so a
    design narrative is never produced for unconfirmed requirements."""
    if state.get("workflow_data", {}).get("recall_offer"):
        logging.info("[EPISODIC_RECALL] Offer pending — short-circuiting to final_response.")
        return "final_response"
    return ["expansion", "solution_build"]

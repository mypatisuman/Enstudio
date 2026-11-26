"""
pid_session_service.py - the P&ID's life across requests.

The solution pipeline is stateless per request. This module gives the P&ID a
life beyond one request:

  load_active          before a solution turn: the session's current drawing,
                       so a modification extends it instead of replacing it
  persist_turn_result  after a solution turn: store a newly produced drawing
                       and stamp it with its session_id and revision
  confirm_pending      POST /api/pid/confirm: apply or cancel deletions the
                       retrofit agent queued for the engineer's approval
  clarify_pending      POST /api/pid/clarify: answer "which subsystem?" and
                       run the modification that was waiting on it

Every engineer decision names the revision it was made against. If the drawing
changed in between -- another tab, another turn -- the decision is refused with
a conflict rather than applied to a drawing the engineer did not see.
"""

from __future__ import annotations

import logging
from typing import Any

from domain.solution.services import subsystem_gate as SG

logger = logging.getLogger(__name__)

#: The only store methods a persisted confirm_delete action may replay. The
#: actions are written by our own agent, but they round-trip through the
#: database, so they are never trusted to name an arbitrary method.
_CONFIRMABLE = {"delete_nodes", "delete_edges"}


class PIDActionError(Exception):
    """A P&ID request that cannot be carried out; `status` is the HTTP code."""

    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


def _repo():
    from common.infra.repositories.pid_graph_repository import pid_graph_repository
    return pid_graph_repository


# ── around a solution turn ──────────────────────────────────────────────────

def load_active(user_id: Any, session_id: str) -> dict[str, Any] | None:
    """The session's current drawing, or None. Never raises: a database
    problem must not stop the engineer's solution request."""
    try:
        return _repo().load_graph(user_id, session_id)
    except Exception as exc:
        logger.warning("[PID_SESSION] could not load P&ID for session %s: %s",
                       session_id, exc)
        return None


def _response_graphs(final_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Every place the response carries the drawing: top level, and inside the
    designed solution the Project page renders from."""
    out = []
    if isinstance(final_response.get("pid_graph"), dict):
        out.append(final_response["pid_graph"])
    designed = final_response.get("designed_solution")
    if isinstance(designed, dict) and isinstance(designed.get("pid_graph"), dict):
        out.append(designed["pid_graph"])
    return out


def persist_turn_result(user_id: Any, session_id: str,
                        final_response: dict[str, Any]) -> dict[str, Any] | None:
    """Store the drawing a solution turn produced, and stamp the response's
    copies with session_id and revision so the P&ID Studio can act on it.

    A graph that already carries a revision is the stored drawing passed
    through unchanged, not a new one, and is not saved again. Never raises."""
    graphs = _response_graphs(final_response)
    fresh = next((g for g in graphs if g.get("revision") is None), None)
    if fresh is None or not session_id:
        return None
    try:
        stored = _repo().save(user_id, session_id, fresh)
    except Exception as exc:
        logger.warning("[PID_SESSION] could not persist P&ID for session %s: %s",
                       session_id, exc)
        return None
    if stored is None:
        logger.warning("[PID_SESSION] P&ID for session %s was saved concurrently; "
                       "this turn's drawing was not stored", session_id)
        return None
    for g in graphs:
        g["session_id"] = session_id
        g["revision"] = stored["revision"]
    logger.info("[PID_SESSION] stored P&ID revision %s for session %s%s",
                stored["revision"], session_id,
                " (pending %s)" % stored["pending_action"]["kind"]
                if stored.get("pending_action") else "")
    return stored


# ── engineer decisions ──────────────────────────────────────────────────────

def _load_for_action(user_id: Any, session_id: str, revision: int | None,
                     kind: str) -> dict[str, Any]:
    if not session_id:
        raise PIDActionError(400, "session_id is required")
    graph = _repo().load_graph(user_id, session_id)
    if graph is None:
        raise PIDActionError(404, "No P&ID is stored for this session")
    if revision is None or int(revision) != graph.get("revision"):
        raise PIDActionError(409, "The P&ID changed since you opened it. Reload it "
                                  "and decide again.", pid_graph=graph)
    pending = graph.get("pending_action") or {}
    if pending.get("kind") != kind:
        raise PIDActionError(400, "This P&ID is not waiting for that decision",
                             pid_graph=graph)
    return graph


def _save_decision(user_id: Any, session_id: str, graph: dict[str, Any],
                   revision: int) -> dict[str, Any]:
    stored = _repo().save(user_id, session_id, graph, expected_revision=revision)
    if stored is None:
        raise PIDActionError(409, "The P&ID changed while your decision was being "
                                  "applied. Reload it and decide again.")
    return stored


def confirm_pending(user_id: Any, session_id: str, revision: int | None,
                    confirmed: bool) -> dict[str, Any]:
    """Apply (confirmed) or discard the deletions the agent queued."""
    from domain.solution.services.pid_builder_service import render_graph
    from domain.solution.services.pid_graph_store import PIDGraphStore

    graph = _load_for_action(user_id, session_id, revision, "confirm_delete")
    pending = graph["pending_action"]
    project_type = graph.get("project_type") or "brownfield"

    if confirmed:
        store = PIDGraphStore(graph, project_type=project_type)
        results = []
        for action in pending.get("actions") or []:
            method = action.get("method")
            if method not in _CONFIRMABLE:
                raise PIDActionError(400, "Refusing to replay %r" % method)
            results.append(getattr(store, method)(**(action.get("args") or {})))
        raw = store.to_graph(summary="Removed %s as confirmed by the engineer."
                                     % ", ".join(pending.get("targets") or []))
        raw["generation_path"] = "engineer_confirmed"
        raw["notes"] = [r for r in results if isinstance(r, str)]
    else:
        raw = {**graph, "summary": "Removal of %s cancelled by the engineer; the "
                                   "drawing is unchanged."
                                   % ", ".join(pending.get("targets") or []),
               "generation_path": "engineer_cancelled", "notes": []}
    raw["pending_action"] = None
    rendered = render_graph(raw, project_type, enrich=False)
    return _save_decision(user_id, session_id, rendered, int(revision))


def clarify_pending(user_id: Any, session_id: str, revision: int | None,
                    answer: str) -> dict[str, Any]:
    """Answer the subsystem question and run the modification that waited on
    it. An unclear answer is refused with the question repeated."""
    from domain.solution.services.pid_builder_service import build_pid_from_solution

    graph = _load_for_action(user_id, session_id, revision, SG.KIND)
    pending = graph["pending_action"]
    outcome, chosen = SG.interpret(answer or "", pending.get("candidates") or [])
    if outcome == "unclear":
        raise PIDActionError(400, "I couldn't tell which subsystem you meant.",
                             question=pending.get("question"))

    instruments, accessories = _session_components(session_id)
    result = build_pid_from_solution(
        requirements=pending.get("request") or "",
        designed_solution=None,
        instruments=instruments,
        accessories=accessories,
        project_type="brownfield_update",
        active_pid_graph={**graph, "pending_action": None},
        user_id=user_id,
        plant_group=(outcome, chosen),
    )
    return _save_decision(user_id, session_id, result, int(revision))


def _session_components(session_id: str) -> tuple[list[dict], list[dict]]:
    """The session's current Bill of Materials, the same source a solution
    turn falls back to when the request carries none."""
    try:
        from common.ai.memory import get_latest_instruments_and_accessories
        data = get_latest_instruments_and_accessories(session_id) or {}
        return list(data.get("instruments") or []), list(data.get("accessories") or [])
    except Exception as exc:
        logger.warning("[PID_SESSION] could not load the BOM for session %s: %s",
                       session_id, exc)
        return [], []

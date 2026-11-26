"""
P&ID graph repository - the current drawing per user + solution session.

WHY THIS EXISTS
---------------
The solution pipeline builds every request's state from scratch
(agentic_integration.run_project_intent) and runs without a checkpointer, so a
P&ID produced in one turn was gone by the next. `active_pid_graph` was never
populated in production: every turn generated a fresh drawing, and the
modify-the-existing-P&ID path (BrownfieldPIDAgent.update_existing_pid) could
not run at all.

One document per (user_id, session_id):

  graph      the validated PIDGraph dict, including its pending_action -- a
             deletion awaiting confirmation or a subsystem question awaiting
             an answer
  revision   incremented on every save; a save that names the revision it
             started from fails when someone else saved in between, so a
             confirmation can never be applied to a drawing that changed
             under it
  history    a capped list of what each revision was (not full copies)

Failures raise; callers in the request path catch and log, because losing the
drawing must never fail the engineer's solution response.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20


class PIDGraphRepository:
    def __init__(self, collection: Any = None) -> None:
        # Injectable for tests; resolved lazily so importing this module never
        # opens a database connection.
        self._collection = collection

    def _col(self):
        if self._collection is not None:
            return self._collection
        from common.infra.mongodb_config import Collections, mongodb_manager
        return mongodb_manager.get_collection(Collections.PID_GRAPHS)

    @staticmethod
    def _key(user_id: Any, session_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "session_id": session_id}

    def load(self, user_id: Any, session_id: str) -> dict[str, Any] | None:
        """The whole document, or None when this session has no drawing."""
        if not session_id:
            return None
        return self._col().find_one(self._key(user_id, session_id))

    def load_graph(self, user_id: Any, session_id: str) -> dict[str, Any] | None:
        """The current graph, stamped with its session_id and revision."""
        doc = self.load(user_id, session_id)
        if not doc or not doc.get("graph"):
            return None
        return {**doc["graph"], "session_id": session_id,
                "revision": doc.get("revision")}

    def save(self, user_id: Any, session_id: str, graph: dict[str, Any], *,
             expected_revision: int | None = None) -> dict[str, Any] | None:
        """Store `graph` as the session's new current revision.

        Returns the stored graph stamped with session_id and revision, or None
        when the save lost a race: either `expected_revision` no longer matches,
        or another writer saved between this call's read and its write.
        """
        if not session_id:
            raise ValueError("session_id is required to store a P&ID")
        col = self._col()
        current = col.find_one(self._key(user_id, session_id))
        current_rev = (current or {}).get("revision") or 0
        if expected_revision is not None and expected_revision != current_rev:
            return None

        revision = current_rev + 1
        now = datetime.now(UTC)
        stored = {**graph, "session_id": session_id, "revision": revision}
        pending = stored.get("pending_action") or {}
        entry = {
            "revision": revision,
            "saved_at": now,
            "summary": str(stored.get("summary") or "")[:200],
            "nodes": len(stored.get("nodes") or []),
            "edges": len(stored.get("edges") or []),
            "project_type": stored.get("project_type"),
            "generation_path": stored.get("generation_path"),
            "pending": pending.get("kind"),
        }
        history = ((current or {}).get("history") or []) + [entry]
        doc = {**self._key(user_id, session_id), "graph": stored,
               "revision": revision, "history": history[-HISTORY_LIMIT:],
               "created_at": (current or {}).get("created_at") or now,
               "updated_at": now}

        if current is None:
            try:
                col.insert_one(doc)
            except Exception as exc:        # unique index: a concurrent first save
                if "duplicate key" in str(exc).lower() or "E11000" in str(exc):
                    return None
                raise
        else:
            res = col.replace_one({"_id": current["_id"], "revision": current_rev}, doc)
            if res.matched_count == 0:
                return None
        return stored

    def history(self, user_id: Any, session_id: str) -> list[dict[str, Any]]:
        doc = self.load(user_id, session_id)
        return list((doc or {}).get("history") or [])


pid_graph_repository = PIDGraphRepository()

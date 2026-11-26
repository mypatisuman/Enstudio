"""Describe workflow state slice."""
from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class DescribeState(TypedDict, total=False):
    project_id: str
    session_id: str
    user_message: str
    intent: str
    messages: Annotated[list[dict], add]   # {"role","content"} transcript
    steps: int
    reply: str | None
    title: str | None
    solution_design: dict | None
    active_solution: dict | None
    holistic_context: dict | None
    ops: Annotated[list[dict], add]        # applied write operations, audited

    # ── Holistic Agent (disambiguation gate, authoring/update only) ────
    # Set before Authoring/Update runs, when the Holistic Agent already
    # resolved which specific pair of cells/nodes the engineer meant —
    # e.g. {"node_a": "n7", "node_b": "n12", "row": 0, "col_a": 1,
    #       "col_b": 2}. Authoring/Update use this instead of re-searching
    # by tag, so they can never disagree with what Holistic resolved.
    resolved_target: dict | None
    # True only while a clarifying question is pending the engineer's
    # answer — lets the router re-enter Holistic on the NEXT message
    # instead of the normal intent classification.
    awaiting_clarification: bool
    clarification_round: int

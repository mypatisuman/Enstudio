"""Describe-side bridge to the Grid Layout Agent.

Wraps agents.extraction.agents.grid_layout so the write specialists
(Authoring, Update, Deletion) can trigger a grid recompute after a
topology-changing mutation, and the read specialists (Query) can report
the current grid to the engineer.

Kept as a thin service, not duplicated logic: the row/column/alignment
math lives in exactly one place (grid_layout.py) and is shared by both
workflows — extraction can call compute_grid() directly on its own
verified nodes/edges; Describe reloads from the DB since its state
doesn't carry the full graph.
"""
from __future__ import annotations


def _load_graph(pid: str) -> tuple[list[dict], list[dict]]:
    from adapters.db import get_db
    db = get_db()
    node_rows = db.execute(
        "SELECT id, kind, kind_detail, label, area, x, y, extra_json "
        "FROM nodes WHERE pid=?", (pid,)).fetchall()
    nodes = [{"id": r[0], "kind": r[1], "kind_detail": r[2], "label": r[3],
             "area": r[4], "x": r[5], "y": r[6], "extra_json": r[7]}
             for r in node_rows]
    edge_rows = db.execute(
        "SELECT from_id, to_id, kind FROM edges WHERE pid=?",
        (pid,)).fetchall()
    edges = [{"from": r[0], "to": r[1], "kind": r[2]} for r in edge_rows]
    return nodes, edges


def recompute_grid(pid: str) -> dict:
    """Recompute and persist the grid from the current DB graph. Safe to
    call after any write — cheap (pure Python graph math, no LLM)."""
    from agents.extraction.agents.grid_layout import compute_grid, save_grid
    nodes, edges = _load_graph(pid)
    grid = compute_grid(nodes, edges)
    save_grid(pid, grid)
    return grid


def get_grid_summary(pid: str) -> dict:
    """Read-only: current grid dimensions + a tag-labeled cell map, for
    the Query agent to answer "what's in row 2" style questions."""
    from agents.extraction.agents.grid_layout import load_grid
    grid = load_grid(pid)
    if not grid["positions"]:
        return {"rows": 0, "cols": 0, "cells": []}

    from adapters.db import get_db
    labels = dict(get_db().execute(
        "SELECT id, label FROM nodes WHERE pid=?", (pid,)).fetchall())
    cells = [{"row": p["row"], "col": p["col"],
             "tag": labels.get(nid) or nid}
             for nid, p in grid["positions"].items()]
    cells.sort(key=lambda c: (c["row"], c["col"]))
    return {"rows": grid["row_count"], "cols": grid["col_count"],
            "cells": cells}


# ── Holistic Agent support: grid-adjacency disambiguation ───────────────────

def find_adjacent_cell_pairs(pid: str, tag_a: str, tag_b: str) -> list[dict]:
    """Every distinct cell-pair where an occurrence of tag_a and an
    occurrence of tag_b are actual neighbors — the disambiguation test
    for "insert X between A and B" when either tag has duplicates or
    multiple distinct neighbors elsewhere in the drawing.

    A pair counts as adjacent if EITHER:
      - they sit in the same grid row with |col_a - col_b| == 1 (visually
        next to each other), OR
      - a real edge in the graph connects them directly (catches cases
        where the grid hasn't been recomputed recently, or the pair
        spans a junction/bend the grid collapsed).

    Matching is exact-tag (==), not substring — "between V-101 and
    E-101" must not match V-101A/V-101B as if they were the same node.
    Returns [] if either tag has zero occurrences (a "does it exist at
    all" problem, distinct from "which one" — the caller reports this
    differently).
    """
    from adapters.db import get_db
    db = get_db()

    def _occurrences(tag: str) -> list[dict]:
        rows = db.execute(
            "SELECT id, label FROM nodes WHERE pid=? AND label=?",
            (pid, tag)).fetchall()
        return [{"id": r[0], "tag": r[1]} for r in rows]

    occ_a, occ_b = _occurrences(tag_a), _occurrences(tag_b)
    if not occ_a or not occ_b:
        return []

    from agents.extraction.agents.grid_layout import load_grid
    grid = load_grid(pid)
    positions = grid["positions"]   # {node_id: {"row", "col"}}

    edge_rows = db.execute(
        "SELECT from_id, to_id FROM edges WHERE pid=?", (pid,)).fetchall()
    edge_pairs = {(r[0], r[1]) for r in edge_rows} | \
        {(r[1], r[0]) for r in edge_rows}

    pairs: list[dict] = []
    seen: set[tuple] = set()
    for a in occ_a:
        for b in occ_b:
            if a["id"] == b["id"]:
                continue
            key = frozenset((a["id"], b["id"]))
            if key in seen:
                continue

            pa, pb = positions.get(a["id"]), positions.get(b["id"])
            grid_adjacent = (pa and pb and pa["row"] == pb["row"]
                             and abs(pa["col"] - pb["col"]) == 1)
            edge_adjacent = (a["id"], b["id"]) in edge_pairs

            if grid_adjacent or edge_adjacent:
                seen.add(key)
                pairs.append({
                    "node_a": a["id"], "node_b": b["id"],
                    "tag_a": a["tag"], "tag_b": b["tag"],
                    "row": pa["row"] if pa else None,
                    "col_a": pa["col"] if pa else None,
                    "col_b": pb["col"] if pb else None,
                    "via": "grid" if grid_adjacent else "edge",
                })
    return pairs

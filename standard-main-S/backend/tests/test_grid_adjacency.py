"""Tests for find_adjacent_cell_pairs() — the Holistic Agent's core
disambiguation primitive. Covers: unambiguous single match, duplicate
tags producing multiple matches, a tag with multiple distinct neighbors,
zero-match ("not connected anywhere"), and the edge-fallback path.
"""
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from agents.describe.services import repository as R  # noqa: E402
from agents.describe.services.grid_service import (  # noqa: E402
    find_adjacent_cell_pairs, recompute_grid)

PID = "hproj"


@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    dbmod.get_db().execute(
        "INSERT INTO projects (id, title) VALUES (?, ?)", (PID, "Test"))
    yield dbmod
    dbmod.close_db()


def test_single_unambiguous_pair(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    recompute_grid(PID)

    pairs = find_adjacent_cell_pairs(PID, "V-101", "E-101")
    assert len(pairs) == 1
    assert pairs[0]["tag_a"] == "V-101" and pairs[0]["tag_b"] == "E-101"
    assert pairs[0]["row"] == 0
    assert abs(pairs[0]["col_a"] - pairs[0]["col_b"]) == 1


def test_duplicate_tags_produce_multiple_matches(db):
    """The exact scenario from the original question: the same two tags
    appear together in more than one place in the drawing."""
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    # A second, independent V-101/E-101 pair on a different line.
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, x, y) VALUES "
        "('n_v2', ?, 'vessel', 'V-101', 0, 0), "
        "('n_e2', ?, 'heat_exchanger', 'E-101', 0, 0)", (PID, PID))
    R.add_edges(PID, [])  # no-op, just documenting: edge added below by id
    R._db().execute(
        "INSERT INTO edges (pid, from_id, to_id, kind) VALUES (?, 'n_v2', 'n_e2', 'stream')",
        (PID,))
    R._db().commit()
    recompute_grid(PID)

    pairs = find_adjacent_cell_pairs(PID, "V-101", "E-101")
    assert len(pairs) == 2   # ambiguous — caller must ask which one


def test_tag_with_multiple_distinct_neighbors_is_not_ambiguous_for_unrelated_pair(db):
    """V-101 sits next to both P-101 and E-201, but ONLY the V-101/E-101
    query should ever be evaluated — a query for V-101+E-101 must not be
    confused by V-101's OTHER neighbors."""
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "P-101", "kind": "pump"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "P-101"},
                      {"from_tag": "P-101", "to_tag": "E-101"}])
    recompute_grid(PID)

    # V-101 and P-101 ARE adjacent (edge-connected directly).
    assert len(find_adjacent_cell_pairs(PID, "V-101", "P-101")) == 1
    # V-101 and E-101 are NOT directly adjacent (P-101 sits between them)
    # — zero, not "found via a two-hop path".
    assert len(find_adjacent_cell_pairs(PID, "V-101", "E-101")) == 0


def test_no_adjacency_returns_empty(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-999", "kind": "heat_exchanger"}])
    recompute_grid(PID)
    assert find_adjacent_cell_pairs(PID, "V-101", "E-999") == []


def test_nonexistent_tag_returns_empty_not_error(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"}])
    recompute_grid(PID)
    assert find_adjacent_cell_pairs(PID, "V-101", "NOPE-999") == []
    assert find_adjacent_cell_pairs(PID, "NOPE-1", "NOPE-2") == []


def test_edge_fallback_when_grid_stale_or_missing(db):
    """A real edge exists but the grid hasn't been recomputed yet (e.g.
    right after a manual DB write bypassing the usual write path) —
    adjacency must still resolve via the edge, not require the grid."""
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    # Deliberately NOT calling recompute_grid(PID) — grid_positions is empty.

    pairs = find_adjacent_cell_pairs(PID, "V-101", "E-101")
    assert len(pairs) == 1
    assert pairs[0]["via"] == "edge"
    assert pairs[0]["row"] is None   # no grid data, but still resolved


def test_same_node_not_paired_with_itself(db):
    """A node whose tag happens to equal both query tags (edge case: a
    self-loop or a tag typo) must never produce a self-pair."""
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"}])
    recompute_grid(PID)
    assert find_adjacent_cell_pairs(PID, "V-101", "V-101") == []

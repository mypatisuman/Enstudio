"""Tests for the Grid Layout Agent (agents/extraction/agents/grid_layout.py)
and its Describe-workflow wiring.
"""
import json
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from agents.extraction.agents import grid_layout as G  # noqa: E402

PID = "gproj"


def node(nid, kind="equipment", area=None, equipment_ref=None):
    n = {"id": nid, "kind": kind, "label": nid}
    if area:
        n["area"] = area
    if equipment_ref:
        n["equipment_ref"] = equipment_ref
    return n


def edge(f, t, kind="stream"):
    return {"from": f, "to": t, "kind": kind}


# ── rows ─────────────────────────────────────────────────────────────────────

def test_single_stream_is_one_row():
    nodes = [node("V-1"), node("P-1"), node("E-1")]
    edges = [edge("V-1", "P-1"), edge("P-1", "E-1")]
    grid = G.compute_grid(nodes, edges)
    rows = {grid["positions"][n]["row"] for n in ("V-1", "P-1", "E-1")}
    assert rows == {0}


def test_two_independent_streams_are_two_rows():
    nodes = [node("V-1"), node("PC-2"), node("PUMP-1"), node("FILT-1")]
    edges = [edge("V-1", "PC-2"), edge("PUMP-1", "FILT-1")]
    grid = G.compute_grid(nodes, edges)
    row_v1 = grid["positions"]["V-1"]["row"]
    row_pc2 = grid["positions"]["PC-2"]["row"]
    row_pump = grid["positions"]["PUMP-1"]["row"]
    assert row_v1 == row_pc2
    assert row_pump != row_v1


def test_disconnected_node_gets_its_own_row():
    nodes = [node("V-1"), node("P-1"), node("ORPHAN")]
    edges = [edge("V-1", "P-1")]
    grid = G.compute_grid(nodes, edges)
    assert grid["positions"]["ORPHAN"]["row"] != grid["positions"]["V-1"]["row"]


# ── columns ──────────────────────────────────────────────────────────────────

def test_columns_follow_flow_order():
    nodes = [node("V-1"), node("P-1"), node("E-1")]
    edges = [edge("V-1", "P-1"), edge("P-1", "E-1")]
    grid = G.compute_grid(nodes, edges)
    cols = [grid["positions"][n]["col"] for n in ("V-1", "P-1", "E-1")]
    assert cols == sorted(cols) == [0, 1, 2]


# ── the exact scenario from the spec ─────────────────────────────────────────

def test_insert_between_two_tiles_shifts_only_that_row():
    """Row 1: vessel -> pressure chamber. Row 2: pump -> filter (unrelated).
    Insert a valve between vessel and chamber -> chamber becomes col 2,
    valve takes col 1 (former chamber slot). Row 2 must NOT shift, because
    nothing in row 2 is aligned to the insertion point (no equipment_ref,
    no shared area)."""
    nodes = [node("V-1"), node("PC-2"), node("PUMP-1"), node("FILT-1")]
    edges = [edge("V-1", "PC-2"), edge("PUMP-1", "FILT-1")]
    before = G.compute_grid(nodes, edges)
    pump_col_before = before["positions"]["PUMP-1"]["col"]
    filt_col_before = before["positions"]["FILT-1"]["col"]

    # "add a valve between V-1 and PC-2" == remove V-1->PC-2, add
    # V-1->VALVE-1->PC-2 (per the authoring prompt's explicit instruction).
    nodes2 = nodes + [node("VALVE-1", kind="valve")]
    edges2 = [edge("V-1", "VALVE-1"), edge("VALVE-1", "PC-2"),
             edge("PUMP-1", "FILT-1")]
    after = G.compute_grid(nodes2, edges2)

    assert after["positions"]["V-1"]["col"] == 0
    assert after["positions"]["VALVE-1"]["col"] == 1
    assert after["positions"]["PC-2"]["col"] == 2          # shifted right
    assert after["positions"]["PC-2"]["row"] == \
        after["positions"]["V-1"]["row"]                    # same row

    # Row 2 (pump/filter) is untouched — the core misalignment fix.
    assert after["positions"]["PUMP-1"]["col"] == pump_col_before
    assert after["positions"]["FILT-1"]["col"] == filt_col_before
    assert after["col_count"] >= before["col_count"] + 1     # n -> n+1


def test_alignment_propagates_via_equipment_ref():
    """A transmitter aligned under its equipment (via equipment_ref) MUST
    shift when its equipment's row grows a column before it."""
    nodes = [node("V-1"), node("VALVE-1", kind="valve"), node("PC-2"),
            node("TT-1", kind="transmitter", equipment_ref="PC-2")]
    edges = [edge("V-1", "VALVE-1"), edge("VALVE-1", "PC-2")]
    grid = G.compute_grid(nodes, edges)
    # TT-1 has no stream edges (instrument), so its own row/col would
    # default elsewhere — the alignment pass must pull it to PC-2's column.
    assert grid["positions"]["TT-1"]["col"] == grid["positions"]["PC-2"]["col"]


def test_alignment_propagates_via_shared_area():
    nodes = [node("V-1", area="100"), node("PC-2", area="100"),
            node("SIDE-1", area="100")]
    edges = [edge("V-1", "PC-2")]
    grid = G.compute_grid(nodes, edges)
    # SIDE-1 shares area "100" with PC-2 -> pulled to the group's max column.
    assert grid["positions"]["SIDE-1"]["col"] == \
        grid["positions"]["PC-2"]["col"]


def test_compaction_removes_empty_columns():
    """Repeated inserts in one row must not leave permanently-empty
    columns behind in the grid dimensions."""
    nodes = [node("A"), node("B")]
    edges = [edge("A", "B")]
    g1 = G.compute_grid(nodes, edges)
    assert g1["col_count"] == 2

    nodes2 = nodes + [node("X")]
    edges2 = [edge("A", "X"), edge("X", "B")]
    g2 = G.compute_grid(nodes2, edges2)
    assert g2["col_count"] == 3          # no gaps introduced


def test_equipment_ref_from_extra_json():
    """DB-sourced nodes carry equipment_ref inside extra_json, not as a
    top-level field — the alignment pass must still find it."""
    nodes = [node("PC-2"),
            {"id": "TT-1", "kind": "transmitter",
             "extra_json": json.dumps({"equipment_ref": "PC-2"})}]
    edges = []
    grid = G.compute_grid(nodes, edges)
    assert grid["positions"]["TT-1"]["col"] == grid["positions"]["PC-2"]["col"]


# ── persistence ──────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    dbmod.get_db().execute(
        "INSERT INTO projects (id, title) VALUES (?, ?)", (PID, "Test"))
    yield dbmod
    dbmod.close_db()


def test_save_and_load_grid_roundtrip(db):
    grid = G.compute_grid([node("A"), node("B")], [edge("A", "B")])
    G.save_grid(PID, grid)
    loaded = G.load_grid(PID)
    assert loaded["positions"] == grid["positions"]
    assert loaded["row_count"] == grid["row_count"]
    assert loaded["col_count"] == grid["col_count"]


def test_save_grid_replaces_previous(db):
    G.save_grid(PID, G.compute_grid([node("A")], []))
    G.save_grid(PID, G.compute_grid([node("A"), node("B")],
                                    [edge("A", "B")]))
    loaded = G.load_grid(PID)
    assert set(loaded["positions"]) == {"A", "B"}


# ── Describe-workflow wiring ─────────────────────────────────────────────────

def test_describe_service_recompute_and_summary(db):
    from agents.describe.services import repository as R
    from agents.describe.services.grid_service import (get_grid_summary,
                                                        recompute_grid)
    R.add_nodes(PID, [{"tag": "V-1", "kind": "vessel"},
                      {"tag": "PC-2", "kind": "vessel"}])
    R.add_edges(PID, [{"from_tag": "V-1", "to_tag": "PC-2"}])
    grid = recompute_grid(PID)
    assert grid["col_count"] == 2

    summary = get_grid_summary(PID)
    tags = {c["tag"] for c in summary["cells"]}
    assert tags == {"V-1", "PC-2"}


def test_authoring_write_triggers_grid_recompute(db, monkeypatch):
    """Recompute happens once per TURN in describe_workflow._dispatch(),
    not per tool call inside the agent loop — so this must drive a full
    turn through run_describe_turn(), not invoke the compiled graph
    directly (which bypasses the workflow layer entirely)."""
    from agents.describe import base as B
    from agents.describe.workflows.describe_workflow import run_describe_turn
    from agents.describe.services.grid_service import get_grid_summary

    it = iter([
        json.dumps({"tool": "add_nodes",
                    "args": {"nodes": [{"tag": "V-1", "kind": "vessel"},
                                       {"tag": "PC-2", "kind": "vessel"}]}}),
        json.dumps({"reply": "Added V-1 and PC-2."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda prompt: next(it))

    run_describe_turn(PID, "add V-1 and PC-2", "s1", use_llm_router=False)

    summary = get_grid_summary(PID)
    assert {c["tag"] for c in summary["cells"]} == {"V-1", "PC-2"}


def test_query_agent_get_grid_tool(db, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from agents.describe import base as B
    from agents.describe.agents.query_agent import build_query_agent
    from agents.describe.services import repository as R
    from agents.describe.services.grid_service import recompute_grid

    R.add_nodes(PID, [{"tag": "V-1", "kind": "vessel"},
                      {"tag": "PC-2", "kind": "vessel"}])
    R.add_edges(PID, [{"from_tag": "V-1", "to_tag": "PC-2"}])
    recompute_grid(PID)

    it = iter([
        json.dumps({"tool": "get_grid", "args": {}}),
        json.dumps({"reply": "The drawing has 1 row and 2 columns."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda prompt: next(it))

    graph = build_query_agent(InMemorySaver())
    final = graph.invoke({"project_id": PID, "session_id": "s2",
                          "user_message": "how many columns?", "steps": 0,
                          "reply": None},
                         {"configurable": {"thread_id": "t2"}})
    assert "2 columns" in final["reply"]
    tool_msgs = [m for m in final["messages"] if m["role"] == "tool"]
    assert '"rows": 1' in tool_msgs[-1]["content"]


# ── H6: branched/cyclic topology rows ────────────────────────────────────────

def test_fanout_split_creates_one_row_per_branch_not_per_node():
    """A split (one node feeding two downstream paths) must produce ONE
    extra row per branch — not a singleton row for every node in every
    unfollowed branch, which is what the old first-successor-only walk
    degenerated into."""
    nodes = [node("FEED"), node("SPLIT"),
            node("A1"), node("A2"), node("A3"),
            node("B1"), node("B2")]
    edges = [edge("FEED", "SPLIT"),
            edge("SPLIT", "A1"), edge("A1", "A2"), edge("A2", "A3"),
            edge("SPLIT", "B1"), edge("B1", "B2")]
    grid = G.compute_grid(nodes, edges)

    row_main = grid["positions"]["FEED"]["row"]
    assert grid["positions"]["SPLIT"]["row"] == row_main
    row_a = grid["positions"]["A1"]["row"]
    assert grid["positions"]["A2"]["row"] == row_a
    assert grid["positions"]["A3"]["row"] == row_a
    row_b = grid["positions"]["B1"]["row"]
    assert grid["positions"]["B2"]["row"] == row_b
    assert row_a != row_b
    # 2 rows total: FEED->SPLIT continues into the first-followed branch
    # (A), so FEED/SPLIT/A1/A2/A3 share one row; B1/B2 form the second.
    # The key assertion is B-branch is ONE row, not two singleton rows
    # (which is what the old first-successor-only walk produced).
    assert grid["row_count"] == 2


def test_recycle_loop_does_not_explode_into_singleton_rows():
    """A pure cycle (recycle stream with no source node — every member
    has indeg > 0) must still walk as a connected chain, not fall
    through to the singleton-row path for every member."""
    nodes = [node("A"), node("B"), node("C")]
    edges = [edge("A", "B"), edge("B", "C"), edge("C", "A")]   # cycle
    grid = G.compute_grid(nodes, edges)

    rows = {grid["positions"][n]["row"] for n in ("A", "B", "C")}
    assert len(rows) == 1     # all three in one row, not three singleton rows


def test_recycle_alongside_a_normal_stream():
    nodes = [node("V-1"), node("P-1"), node("R-1"),
            node("A"), node("B"), node("C")]
    edges = [edge("V-1", "P-1"), edge("P-1", "R-1"),
            edge("A", "B"), edge("B", "C"), edge("C", "A")]
    grid = G.compute_grid(nodes, edges)

    main_rows = {grid["positions"][n]["row"] for n in ("V-1", "P-1", "R-1")}
    cycle_rows = {grid["positions"][n]["row"] for n in ("A", "B", "C")}
    assert len(main_rows) == 1
    assert len(cycle_rows) == 1
    assert main_rows != cycle_rows
    assert grid["row_count"] == 2


def test_multi_way_fanout_all_branches_get_own_row():
    """3-way split — every branch after the first-followed one must get
    its own row (regression guard: earlier the walk only queued nxts[1:],
    i.e. would have missed a 3rd+ branch if sliced wrong)."""
    nodes = [node("HUB"), node("X1"), node("Y1"), node("Z1")]
    edges = [edge("HUB", "X1"), edge("HUB", "Y1"), edge("HUB", "Z1")]
    grid = G.compute_grid(nodes, edges)

    rows = {grid["positions"][n]["row"] for n in ("X1", "Y1", "Z1")}
    hub_row = grid["positions"]["HUB"]["row"]
    all_rows = rows | {hub_row}
    assert len(all_rows) == 3   # HUB shares a row with exactly one branch


def test_parallel_twin_equipment_share_baseline_row():
    """Twin reactors R-110A and R-110B must share the same baseline row
    and sit on distinct columns (side-by-side) rather than vertical stacking."""
    nodes = [node("FEED"), node("R-110A", kind="reactor"), node("R-110B", kind="reactor"), node("EFF")]
    edges = [edge("FEED", "R-110A"), edge("FEED", "R-110B"), edge("R-110A", "EFF"), edge("R-110B", "EFF")]
    grid = G.compute_grid(nodes, edges)

    row_a = grid["positions"]["R-110A"]["row"]
    row_b = grid["positions"]["R-110B"]["row"]
    col_a = grid["positions"]["R-110A"]["col"]
    col_b = grid["positions"]["R-110B"]["col"]

    assert row_a == row_b, "Parallel twin reactors must share the same horizontal baseline row"
    assert col_a != col_b, "Parallel twin reactors must occupy distinct horizontal columns"


def test_multipoint_sensor_arrays_grouped():
    """Multi-element thermocouple arrays (TI-1103A..H) must group under their
    parent equipment rather than consuming 8 independent stream rows."""
    nodes = [node("R-110A", kind="reactor")]
    for letter in "ABCDEFGH":
        nodes.append(node(f"TI-1103{letter}", kind="transmitter", equipment_ref="R-110A"))
    edges = []
    grid = G.compute_grid(nodes, edges)

    parent_row = grid["positions"]["R-110A"]["row"]
    # All 8 sensors are clustered within parent's band (at most 2 rows), not 8 separate rows
    sensor_rows = {grid["positions"][f"TI-1103{l}"]["row"] for l in "ABCDEFGH"}
    assert len(sensor_rows) <= 2
    assert grid["row_count"] <= 3


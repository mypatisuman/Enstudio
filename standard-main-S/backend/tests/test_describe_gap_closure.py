"""Tests for the four gaps closed against the Flask/MCP/Rust capability
survey: edge delete/update, proposal review, loop awareness.

- G1: delete_edges, update_edge (Deletion/Update agents)
- G2: list_proposals, review_proposal (Update/Validation agents)
- G3: get_loops, check_loop_completeness (Query/Validation agents)
"""
import json
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from agents.describe import base as B  # noqa: E402
from agents.describe.services import repository as R  # noqa: E402

PID = "gapproj"


@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    dbmod.get_db().execute(
        "INSERT INTO projects (id, title) VALUES (?, ?)", (PID, "Test"))
    yield dbmod
    dbmod.close_db()


def _script_llm(monkeypatch, responses: list[str]):
    it = iter(responses)
    monkeypatch.setattr(B, "llm_complete", lambda prompt: next(it))


# ── G1: delete_edges ─────────────────────────────────────────────────────────

def test_delete_edges_removes_only_the_edge_not_the_nodes(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "P-101", "kind": "pump"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "P-101"}])

    result = R.delete_edges(PID, "V-101", "P-101")
    assert "Deleted 1 edge" in result
    assert R.get_connections(PID, "V-101") == []
    assert not R.get_node(PID, "V-101").get("error")   # node still exists
    assert not R.get_node(PID, "P-101").get("error")


def test_delete_edges_works_reverse_direction(db):
    R.add_nodes(PID, [{"tag": "A", "kind": "vessel"},
                      {"tag": "B", "kind": "pump"}])
    R.add_edges(PID, [{"from_tag": "A", "to_tag": "B"}])
    result = R.delete_edges(PID, "B", "A")   # reversed order
    assert "Deleted 1 edge" in result


def test_delete_edges_missing_endpoint_errors(db):
    R.add_nodes(PID, [{"tag": "A", "kind": "vessel"}])
    assert R.delete_edges(PID, "A", "NOPE").startswith("ERROR")


def test_delete_edges_no_such_edge_errors(db):
    R.add_nodes(PID, [{"tag": "A", "kind": "vessel"},
                      {"tag": "B", "kind": "pump"}])
    assert R.delete_edges(PID, "A", "B").startswith("ERROR")


def test_deletion_agent_owns_delete_edges(db, monkeypatch):
    from agents.describe.agents.deletion_agent import build_deletion_agent, TOOLS
    assert "delete_edges" in TOOLS
    assert TOOLS["delete_edges"]["requires_confirmation"] is True

    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "P-101", "kind": "pump"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "P-101"}])
    it = iter([
        json.dumps({"tool": "delete_edges",
                    "args": {"from_tag": "V-101", "to_tag": "P-101"}}),
        json.dumps({"reply": "Removed the connection."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda p: next(it))

    graph = build_deletion_agent(InMemorySaver())
    paused = graph.invoke(
        {"project_id": PID, "session_id": "s1", "user_message": "delete "
         "the connection between V-101 and P-101", "steps": 0, "reply": None},
        {"configurable": {"thread_id": "t1"}})
    assert "__interrupt__" in paused
    payload = paused["__interrupt__"][0].value
    assert payload["tool"] == "delete_edges"
    assert set(payload["tags"]) == {"V-101", "P-101"}
    assert R.get_connections(PID, "V-101") != []   # not yet deleted

    from langgraph.types import Command
    final = graph.invoke(Command(resume={"confirmed": True}),
                         {"configurable": {"thread_id": "t1"}})
    assert final["reply"] == "Removed the connection."
    assert R.get_connections(PID, "V-101") == []


# ── G1: update_edge ──────────────────────────────────────────────────────────

def test_update_edge_reclassifies_kind(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "FIC-101", "kind": "controller"}])
    R.add_edges(PID, [{"from_tag": "FT-101", "to_tag": "FIC-101",
                       "kind": "stream"}])
    result = R.update_edge(PID, "FT-101", "FIC-101", kind="signal")
    assert "kind=signal" in result
    conns = R.get_connections(PID, "FT-101")
    assert conns[0]["kind"] == "signal"
    # The mirrored `connections` row (what export_vids actually reads) must
    # reflect the reclassification too, not just the `edges` table.
    ctype = R._db().execute(
        "SELECT type FROM connections WHERE pid=? AND from_tag='FT-101' "
        "AND to_tag='FIC-101'", (PID,)).fetchone()
    assert ctype is not None and ctype[0] == "signal"


def test_update_edge_no_kind_errors(db):
    R.add_nodes(PID, [{"tag": "A", "kind": "vessel"},
                      {"tag": "B", "kind": "pump"}])
    R.add_edges(PID, [{"from_tag": "A", "to_tag": "B"}])
    assert R.update_edge(PID, "A", "B").startswith("ERROR")


def test_update_edge_missing_edge_errors(db):
    R.add_nodes(PID, [{"tag": "A", "kind": "vessel"},
                      {"tag": "B", "kind": "pump"}])
    assert R.update_edge(PID, "A", "B", kind="signal").startswith("ERROR")


def test_update_agent_owns_update_edge(db, monkeypatch):
    from agents.describe.agents.update_agent import build_update_agent, TOOLS
    assert "update_edge" in TOOLS

    R.add_nodes(PID, [{"tag": "A", "kind": "vessel"},
                      {"tag": "B", "kind": "pump"}])
    R.add_edges(PID, [{"from_tag": "A", "to_tag": "B", "kind": "stream"}])
    it = iter([
        json.dumps({"tool": "update_edge",
                    "args": {"from_tag": "A", "to_tag": "B",
                            "kind": "bypass"}}),
        json.dumps({"reply": "Reclassified as bypass."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda p: next(it))
    graph = build_update_agent(InMemorySaver())
    final = graph.invoke(
        {"project_id": PID, "session_id": "s2", "user_message":
         "mark A-B as a bypass", "steps": 0, "reply": None},
        {"configurable": {"thread_id": "t2"}})
    assert final["reply"] == "Reclassified as bypass."
    assert R.get_connections(PID, "A")[0]["kind"] == "bypass"


# ── G2: proposal review ──────────────────────────────────────────────────────

def _insert_proposal(pid, node_id, ptype, original, proposed,
                     confidence=0.85, method="fuzzy_match",
                     review_state=None):
    R._db().execute(
        "INSERT INTO proposals (pid, node_id, type, original, proposed, "
        "confidence, method, review_state, extra_json) VALUES "
        "(?,?,?,?,?,?,?,?,?)",
        (pid, node_id, ptype, original, proposed, confidence, method,
         review_state, "{}"))
    R._db().commit()


def test_list_proposals_excludes_resolved(db):
    _insert_proposal(PID, "n1", "tag", "FT-1O1", "FT-101")
    _insert_proposal(PID, "n2", "tag", "PT-2O2", "PT-202",
                     review_state="accepted")
    pending = R.list_proposals(PID)
    assert len(pending) == 1
    assert pending[0]["node_id"] == "n1"


def test_list_proposals_filters_by_type(db):
    _insert_proposal(PID, "n1", "tag", "FT-1O1", "FT-101")
    _insert_proposal(PID, "n2", "connection", "n2", "V-101")
    assert len(R.list_proposals(PID, "tag")) == 1
    assert len(R.list_proposals(PID, "connection")) == 1
    assert len(R.list_proposals(PID)) == 2


def test_review_proposal_accept_tag_renames_node(db):
    R.add_nodes(PID, [{"tag": "FT-1O1", "kind": "transmitter"}])
    _insert_proposal(PID, "FT-1O1", "tag", "FT-1O1", "FT-101")

    result = R.review_proposal(PID, "FT-1O1", "tag", accept=True)
    assert "Accepted" in result
    assert not R.get_node(PID, "FT-101").get("error")

    row = R._db().execute(
        "SELECT review_state FROM proposals WHERE pid=? AND node_id=?",
        (PID, "FT-1O1")).fetchone()
    assert row[0] == "accepted"


def test_review_proposal_reject_does_not_mutate_graph(db):
    R.add_nodes(PID, [{"tag": "FT-1O1", "kind": "transmitter"}])
    _insert_proposal(PID, "FT-1O1", "tag", "FT-1O1", "FT-101")

    R.review_proposal(PID, "FT-1O1", "tag", accept=False)
    assert not R.get_node(PID, "FT-1O1").get("error")   # unchanged
    assert R.get_node(PID, "FT-101").get("error")        # never renamed

    row = R._db().execute(
        "SELECT review_state FROM proposals WHERE pid=? AND node_id=?",
        (PID, "FT-1O1")).fetchone()
    assert row[0] == "rejected"


def test_review_proposal_accept_connection_adds_edge(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "V-101", "kind": "vessel"}])
    _insert_proposal(PID, "FT-101", "connection", "FT-101", "V-101")

    R.review_proposal(PID, "FT-101", "connection", accept=True)
    assert any(c["other"] == "V-101" for c in R.get_connections(PID, "FT-101"))


def test_review_proposal_not_found_errors(db):
    assert R.review_proposal(PID, "nope", "tag", accept=True).startswith("ERROR")


def test_update_agent_owns_proposal_review(db, monkeypatch):
    from agents.describe.agents.update_agent import build_update_agent, TOOLS
    assert "list_proposals" in TOOLS and "review_proposal" in TOOLS

    R.add_nodes(PID, [{"tag": "FT-1O1", "kind": "transmitter"}])
    _insert_proposal(PID, "FT-1O1", "tag", "FT-1O1", "FT-101")
    it = iter([
        json.dumps({"tool": "list_proposals", "args": {}}),
        json.dumps({"tool": "review_proposal",
                    "args": {"node_id": "FT-1O1", "proposal_type": "tag",
                            "accept": True}}),
        json.dumps({"reply": "Accepted the tag correction."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda p: next(it))
    graph = build_update_agent(InMemorySaver())
    final = graph.invoke(
        {"project_id": PID, "session_id": "s3", "user_message":
         "accept the suggested tag correction", "steps": 0, "reply": None},
        {"configurable": {"thread_id": "t3"}})
    assert final["reply"] == "Accepted the tag correction."
    assert not R.get_node(PID, "FT-101").get("error")


# ── G3: loop awareness ───────────────────────────────────────────────────────

def _add_instrument_row(pid, tag, area, itype):
    # REPLACE, not a bare INSERT: R.add_nodes() now mirrors a
    # transmitter/controller/etc-kind tag into `instruments` itself (see
    # repository.py's _mirror_node_to_instrument_or_equipment) — this
    # fixture overwrites that auto-mirrored row with its own specific
    # area/type values rather than colliding with it.
    R._db().execute(
        "INSERT OR REPLACE INTO instruments (tag, pid, area, kind_detail, type) "
        "VALUES (?,?,?,?,?)", (tag, pid, area, itype, itype))
    R._db().commit()


def _add_control_valve(pid, tag):
    """A control valve is read from `nodes` (kind='valve'), not
    `instruments` — infer_loops's final_element resolution falls back to
    valve_nodes indexed by (variable, number) parsed from an *CV-\\d+ tag."""
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, x, y) VALUES "
        "(?,?,?,?,0,0)", (tag, pid, "valve", tag))
    R._db().commit()


def test_get_loops_complete_loop(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "FIC-101", "kind": "controller"}])
    _add_instrument_row(PID, "FT-101", "100", "transmitter")
    _add_instrument_row(PID, "FIC-101", "100", "controller")
    _add_control_valve(PID, "FCV-101")

    loops = R.get_loops(PID)
    assert len(loops) == 1
    assert loops[0]["status"] == "complete"


def test_get_loops_filters_by_status(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "FIC-101", "kind": "controller"},
                      {"tag": "PT-202", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101", "100", "transmitter")
    _add_instrument_row(PID, "FIC-101", "100", "controller")
    _add_control_valve(PID, "FCV-101")
    _add_instrument_row(PID, "PT-202", "200", "transmitter")   # no controller

    complete = R.get_loops(PID, status_filter="complete")
    no_ctrl = R.get_loops(PID, status_filter="no_controller")
    assert len(complete) == 1
    assert len(no_ctrl) == 1
    assert no_ctrl[0]["loop_id"] != complete[0]["loop_id"]


def test_check_loop_completeness_summary(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "FIC-101", "kind": "controller"},
                      {"tag": "PT-202", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101", "100", "transmitter")
    _add_instrument_row(PID, "FIC-101", "100", "controller")
    _add_control_valve(PID, "FCV-101")
    _add_instrument_row(PID, "PT-202", "200", "transmitter")

    summary = R.check_loop_completeness(PID)
    assert summary["total"] == 2
    assert summary["by_status"]["complete"] == 1
    assert summary["by_status"]["no_controller"] == 1


def test_get_loops_empty_project_returns_empty_list(db):
    assert R.get_loops(PID) == []
    assert R.check_loop_completeness(PID) == {"total": 0, "by_status": {}}


def test_query_agent_owns_get_loops(db, monkeypatch):
    from agents.describe.agents.query_agent import build_query_agent, TOOLS
    assert "get_loops" in TOOLS

    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "FIC-101", "kind": "controller"}])
    _add_instrument_row(PID, "FT-101", "100", "transmitter")
    _add_instrument_row(PID, "FIC-101", "100", "controller")
    _add_control_valve(PID, "FCV-101")

    it = iter([
        json.dumps({"tool": "get_loops", "args": {}}),
        json.dumps({"reply": "1 complete loop found."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda p: next(it))
    graph = build_query_agent(InMemorySaver())
    final = graph.invoke(
        {"project_id": PID, "session_id": "s4", "user_message":
         "are there any control loops?", "steps": 0, "reply": None},
        {"configurable": {"thread_id": "t4"}})
    assert final["reply"] == "1 complete loop found."
    tool_msgs = [m for m in final["messages"] if m["role"] == "tool"]
    assert '"status": "complete"' in tool_msgs[-1]["content"]


def test_validation_agent_owns_loop_and_proposal_reads(db, monkeypatch):
    from agents.describe.agents.validation_agent import build_validation_agent, TOOLS
    assert "check_loop_completeness" in TOOLS
    assert "list_proposals" in TOOLS

    it = iter([
        json.dumps({"tool": "check_loop_completeness", "args": {}}),
        json.dumps({"reply": "No loops yet."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda p: next(it))
    graph = build_validation_agent(InMemorySaver())
    final = graph.invoke(
        {"project_id": PID, "session_id": "s5", "user_message":
         "check loop completeness", "steps": 0, "reply": None},
        {"configurable": {"thread_id": "t5"}})
    assert final["reply"] == "No loops yet."

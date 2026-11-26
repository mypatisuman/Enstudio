"""Tests for the dedicated-agent Describe workflow (agents/describe/).

Runs against a real temporary studio.db with the LLM scripted — no API
keys needed. The router runs in rules-only mode (use_llm_router=False).
"""
import json
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from agents.describe.services import repository as R  # noqa: E402
from agents.describe import base as B  # noqa: E402
from agents.describe.workflows import describe_workflow as S
from agents.describe.agents import router as RT  # noqa: E402

PID = "dproj"


@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    dbmod.get_db().execute(
        "INSERT INTO projects (id, title) VALUES (?, ?)", (PID, "Test"))
    yield dbmod
    dbmod.close_db()


@pytest.fixture()
def graphs():
    """One InMemorySaver shared by all specialists, so a paused deletion
    can be resumed within a test."""
    cp = InMemorySaver()
    return {intent: builder(cp) for intent, builder in S._BUILDERS.items()}


def _script_llm(monkeypatch, responses: list[str]):
    it = iter(responses)
    monkeypatch.setattr(B, "llm_complete", lambda prompt: next(it))


def _turn(pid, message, session, graphs):
    return S.run_describe_turn(pid, message, session, graphs=graphs,
                               use_llm_router=False)


# ── repository (shared data layer) ───────────────────────────────────────────

def test_repository_roundtrip(db):
    assert R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                             {"tag": "P-101", "kind": "pump"}]).startswith("Added 2")
    assert R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"}]) \
        .startswith("ERROR: tags already exist")
    assert R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "P-101"}]) \
        .startswith("Added 1")
    assert R.get_connections(PID, "V-101") == \
        [{"direction": "out", "other": "P-101", "kind": "stream"}]

    # ── Gap-fix coverage: create path must mirror into instruments/
    # equipment/connections, the tables export_vids/export_ympl/
    # export_markdown and the Sidebar/Review screens actually read —
    # nodes/edges alone are only visible on the live Canvas.
    dbc = db.get_db()
    assert dbc.execute(
        "SELECT tag FROM equipment WHERE pid=? AND tag='V-101'", (PID,)
    ).fetchone() is not None, "vessel (equipment kind) must mirror into equipment"
    assert dbc.execute(
        "SELECT tag FROM equipment WHERE pid=? AND tag='P-101'", (PID,)
    ).fetchone() is not None, "pump (equipment kind) must mirror into equipment"
    conn_row = dbc.execute(
        "SELECT from_tag, to_tag, type FROM connections WHERE pid=? AND "
        "from_tag='V-101' AND to_tag='P-101'", (PID,)
    ).fetchone()
    assert tuple(conn_row) == ("V-101", "P-101", "stream")

    assert R.update_node(PID, "P-101", new_tag="P-101A").startswith("Updated")
    # rename must cascade the mirror too (pre-existing behavior, still true)
    assert dbc.execute(
        "SELECT tag FROM equipment WHERE pid=? AND tag='P-101A'", (PID,)
    ).fetchone() is not None
    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=? AND to_tag='P-101'", (PID,)
    ).fetchone() is None, "stale pre-rename tag must not linger in connections"

    v = R.validate_drawing(PID)
    assert v["nodes"] == 2 and v["duplicate_tags"] == 0
    assert R.delete_nodes(PID, ["V-101"]).startswith("Deleted 1")
    assert R.get_connections(PID, "P-101A") == []
    assert dbc.execute(
        "SELECT 1 FROM equipment WHERE pid=? AND tag='V-101'", (PID,)
    ).fetchone() is None, "delete must cascade the mirror too"
    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=?", (PID,)
    ).fetchone() is None, "no connections should survive both endpoints/edge gone"


def test_add_nodes_mirrors_instrument_kind(db):
    """A Describe-authored instrument-kind tag (per _is_instrument_kind,
    ported from the Rust desktop write path) must land in `instruments`,
    not `equipment` — this is what export_vids' separate instruments:
    section and the Review screen's instrument list actually read."""
    R.add_nodes(PID, [{"tag": "PT-101", "kind": "transmitter", "area": "100"}])
    dbc = db.get_db()
    assert tuple(dbc.execute(
        "SELECT area FROM instruments WHERE pid=? AND tag='PT-101'", (PID,)
    ).fetchone()) == ("100",)
    assert dbc.execute(
        "SELECT 1 FROM equipment WHERE pid=? AND tag='PT-101'", (PID,)
    ).fetchone() is None, "an instrument-kind tag must not also land in equipment"


def test_insert_between_mirrors_and_removes_stale_connection(db):
    """insert_between's atomic A->new->B rewrite (with stale direct-edge
    removal) must apply the same mirroring/unmirroring to connections that
    it already applies to edges, or the exported connectivity would still
    show the old direct A-B pipe alongside the new A-new-B routing."""
    R.add_nodes(PID, [{"tag": "V-201", "kind": "vessel"},
                      {"tag": "V-202", "kind": "vessel"}])
    R.add_edges(PID, [{"from_tag": "V-201", "to_tag": "V-202", "kind": "stream"}])
    dbc = db.get_db()
    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=? AND from_tag='V-201' AND "
        "to_tag='V-202'", (PID,)
    ).fetchone() is not None

    result = R.insert_between(
        PID, {"tag": "HV-201", "kind": "valve"}, "V-201", "V-202")
    assert "removed the old direct edge" in result

    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=? AND from_tag='V-201' AND "
        "to_tag='V-202'", (PID,)
    ).fetchone() is None, "the superseded direct A-B connection must be removed"
    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=? AND from_tag='V-201' AND "
        "to_tag='HV-201'", (PID,)
    ).fetchone() is not None
    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=? AND from_tag='HV-201' AND "
        "to_tag='V-202'", (PID,)
    ).fetchone() is not None
    assert dbc.execute(
        "SELECT 1 FROM equipment WHERE pid=? AND tag='HV-201'", (PID,)
    ).fetchone() is not None


def test_delete_edges_removes_mirrored_connection(db):
    """delete_edges (single-edge delete) must remove the matching
    connections row too — this was the one CRUD path where even the
    node-level rename/delete cascades didn't reach, since it deletes an
    edge without touching either endpoint node."""
    R.add_nodes(PID, [{"tag": "V-301", "kind": "vessel"},
                      {"tag": "P-301", "kind": "pump"}])
    R.add_edges(PID, [{"from_tag": "V-301", "to_tag": "P-301"}])
    dbc = db.get_db()
    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=? AND from_tag='V-301' AND "
        "to_tag='P-301'", (PID,)
    ).fetchone() is not None

    assert R.delete_edges(PID, "V-301", "P-301").startswith("Deleted 1")
    assert dbc.execute(
        "SELECT 1 FROM connections WHERE pid=? AND from_tag='V-301' AND "
        "to_tag='P-301'", (PID,)
    ).fetchone() is None


# ── router (deterministic rules) ─────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("add a feed drum V-101 and pump P-101", "authoring"),
    ("delete V-9 please", "deletion"),
    ("rename TT-205 to TT-205A", "update"),
    ("check the drawing quality", "validation"),
    ("design a cascade temperature control solution for reactor R-101", "solution"),
    ("what pumps do we have?", "query"),
    ("hmm interesting diagram", "query"),          # no verb -> read-only
])
def test_router_rules(db, message, expected):
    intent, _reason, controller = RT.route_message(PID, message, use_llm=False)
    assert intent == expected
    assert controller == "rules"


# ── dedicated agents ─────────────────────────────────────────────────────────

def test_authoring_flow(db, graphs, monkeypatch):
    _script_llm(monkeypatch, [
        json.dumps({"thought": "check", "tool": "search_graph",
                    "args": {"query": "V-101"}}),
        json.dumps({"tool": "add_nodes",
                    "args": {"nodes": [{"tag": "V-101", "kind": "vessel"}]}}),
        json.dumps({"reply": "Added feed drum V-101.",
                    "title": "Feed drum setup"}),
    ])
    final = _turn(PID, "add a feed drum V-101", "s1", graphs)
    assert final["agent"] == "authoring"
    assert final["reply"] == "Added feed drum V-101."
    assert len(final["ops"]) == 1 and final["ops"][0]["tool"] == "add_nodes"
    assert R.get_node(PID, "V-101")["kind"] == "vessel"


def test_agent_boundary_tool_rejected(db, graphs, monkeypatch):
    """The authoring agent does NOT own delete_nodes — a scripted attempt
    to call it must be rejected in-loop, and nothing is deleted."""
    R.add_nodes(PID, [{"tag": "V-9", "kind": "vessel"}])
    _script_llm(monkeypatch, [
        json.dumps({"tool": "delete_nodes", "args": {"tags": ["V-9"]}}),
        json.dumps({"reply": "I can only add elements — deletion is a "
                             "separate request."}),
    ])
    # Message routes to authoring; the scripted model misbehaves and tries
    # a delete anyway — the agent boundary must reject it.
    final = _turn(PID, "add a relief valve near V-9", "s2", graphs)
    assert final["agent"] == "authoring"
    assert not R.get_node(PID, "V-9").get("error")     # still exists
    tool_msgs = [m for m in final["messages"] if m["role"] == "tool"]
    assert any("not available to the authoring_agent" in m["content"]
               for m in tool_msgs)


def test_update_flow_reacts_to_error(db, graphs, monkeypatch):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "FT-102", "kind": "transmitter"}])
    _script_llm(monkeypatch, [
        json.dumps({"tool": "update_node",
                    "args": {"tag": "FT-101", "new_tag": "FT-102"}}),
        json.dumps({"reply": "FT-102 is taken — no change made."}),
    ])
    final = _turn(PID, "rename FT-101 to FT-102", "s3", graphs)
    assert final["agent"] == "update"
    assert "taken" in final["reply"]
    assert not final.get("ops")
    assert R.get_node(PID, "FT-101")["kind"] == "transmitter"  # unchanged


def test_deletion_interrupt_confirm_and_cancel(db, graphs, monkeypatch):
    R.add_nodes(PID, [{"tag": "V-9", "kind": "vessel"},
                      {"tag": "V-8", "kind": "vessel"}])
    _script_llm(monkeypatch, [
        json.dumps({"tool": "delete_nodes",
                    "args": {"tags": ["V-9"], "reason": "engineer asked"}}),
        json.dumps({"reply": "Deleted V-9."}),
    ])
    paused = _turn(PID, "delete V-9", "s4", graphs)
    assert paused["agent"] == "deletion"
    assert "__interrupt__" in paused
    payload = paused["__interrupt__"][0].value
    assert payload["tags"] == ["V-9"] and payload["agent"] == "deletion_agent"
    assert not R.get_node(PID, "V-9").get("error")     # NOT deleted yet

    final = S.resolve_describe_turn(PID, "s4", True, graphs=graphs)
    assert final["reply"] == "Deleted V-9."
    assert R.get_node(PID, "V-9").get("error")         # gone

    _script_llm(monkeypatch, [
        json.dumps({"tool": "delete_nodes", "args": {"tags": ["V-8"]}}),
        json.dumps({"reply": "Okay, V-8 kept."}),
    ])
    paused = _turn(PID, "remove V-8", "s5", graphs)
    assert "__interrupt__" in paused
    final = S.resolve_describe_turn(PID, "s5", False, graphs=graphs)
    assert "kept" in final["reply"]
    assert not R.get_node(PID, "V-8").get("error")     # still there


def test_validation_flow(db, graphs, monkeypatch):
    R.add_nodes(PID, [{"tag": "V-1", "kind": "vessel"}])   # orphan
    _script_llm(monkeypatch, [
        json.dumps({"tool": "validate_drawing", "args": {}}),
        json.dumps({"reply": "Score below 100: V-1 is an orphan."}),
    ])
    final = _turn(PID, "check the drawing quality", "s6", graphs)
    assert final["agent"] == "validation"
    tool_msgs = [m for m in final["messages"] if m["role"] == "tool"]
    assert '"orphans": 1' in tool_msgs[-1]["content"]


def test_step_bound(db, graphs, monkeypatch):
    looping = json.dumps({"tool": "search_graph", "args": {"query": "x"}})
    _script_llm(monkeypatch, [looping] * (B.MAX_STEPS + 2))
    final = _turn(PID, "what pumps do we have?", "s7", graphs)
    assert final["agent"] == "query"
    assert "step limit" in final["reply"]


def test_garbage_llm_output_degrades(db, graphs, monkeypatch):
    _script_llm(monkeypatch, ["not json at all, just prose"])
    final = _turn(PID, "what is here?", "s8", graphs)
    assert final["reply"].startswith("not json")


def test_solution_flow(db, graphs, monkeypatch):
    R.add_nodes(PID, [{"tag": "R-101", "kind": "reactor"}])
    _script_llm(monkeypatch, [
        json.dumps({"thought": "inspect reactor", "tool": "search_graph",
                    "args": {"query": "R-101"}}),
        json.dumps({"thought": "add temperature transmitter", "tool": "add_nodes",
                    "args": {"nodes": [{"tag": "TT-101", "kind": "instrument", "description": "Temperature Transmitter"}]}}),
        json.dumps({
            "reply": "Designed cascade temperature control solution for R-101.",
            "solution_design": {
                "project_objective": "Precise exothermic temperature regulation of R-101",
                "design_overview": "Cascade temperature-to-jacket coolant flow control architecture.",
                "component_roles": [
                    {"name": "TT-101", "category": "Temperature Transmitter", "purpose": "Primary reactor temperature measurement"}
                ],
                "optimizations": ["1oo2 SIL 2 voting on high temperature trip"],
                "design_considerations": ["Exothermic runaway prevention"],
                "assumptions": ["Jacket utility water supply pressure is constant"]
            },
            "title": "R-101 Temperature Control"
        }),
    ])
    final = _turn(PID, "design a temperature control solution for R-101", "s9", graphs)
    assert final["agent"] == "solution"
    assert len(final["ops"]) == 1
    assert final["ops"][0]["tool"] == "add_nodes"
    assert "Designed cascade" in final["reply"]


def test_edge_kind_normalization_and_topology(db):
    R.add_nodes(PID, [
        {"tag": "REACTOR-FEED-HDR", "kind": "header"},
        {"tag": "PI-1180", "kind": "indicator"},
        {"tag": "M-116", "kind": "mixer"},
        {"tag": "PSV-1111", "kind": "relief_valve"},
        {"tag": "VENT-HDR", "kind": "header"},
        {"tag": "TT-101", "kind": "transmitter"},
        {"tag": "TIC-101", "kind": "controller"},
        {"tag": "TCV-101", "kind": "control_valve"},
    ])
    # Add various connection pairs with default/mixed kinds
    R.add_edges(PID, [
        {"from_tag": "REACTOR-FEED-HDR", "to_tag": "M-116", "kind": "stream"},
        {"from_tag": "REACTOR-FEED-HDR", "to_tag": "PI-1180", "kind": "stream"}, # Auto-normalized to impulse
        {"from_tag": "PSV-1111", "to_tag": "VENT-HDR", "kind": "stream"},        # Auto-normalized to relief
        {"from_tag": "TT-101", "to_tag": "TIC-101", "kind": "stream"},           # Auto-normalized to signal
        {"from_tag": "TIC-101", "to_tag": "TCV-101", "kind": "stream"},          # Auto-normalized to pneumatic
    ])
    
    # Verify in DB
    rows = db.get_db().execute("SELECT from_id, to_id, kind FROM edges WHERE pid=?", (PID,)).fetchall()
    kinds = {(r[0], r[1]): r[2] for r in rows}
    
    assert kinds[("REACTOR-FEED-HDR", "M-116")] == "stream"
    assert kinds[("REACTOR-FEED-HDR", "PI-1180")] == "impulse"
    assert kinds[("PSV-1111", "VENT-HDR")] == "relief"
    assert kinds[("TT-101", "TIC-101")] == "signal"
    assert kinds[("TIC-101", "TCV-101")] == "pneumatic"


def test_layout_plan_corridor_synthesis(db, graphs, monkeypatch):
    _script_llm(monkeypatch, [
        json.dumps({
            "reply": "Synthesized complete reactor feed system.",
            "solution_design": {
                "inferred_plant_type": "Catalytic Feed Ingress & Overpressure Protection",
                "unit_operations": ["Feed Ingress", "Inline Static Mixing", "Safety Relief", "Bypass Diversion"],
                "component_roles": [
                    {"name": "PSV-1111", "category": "Safety Relief Valve", "purpose": "Overpressure protection"},
                    {"name": "REACTOR-FEED-HDR", "category": "Process Header", "purpose": "Main feed ingress"},
                    {"name": "M-116", "category": "Static Mixer", "purpose": "Turbulent component blending"},
                    {"name": "R-110A", "category": "Packed Bed Reactor", "purpose": "Catalytic conversion"},
                    {"name": "HE-112", "category": "Heat Exchanger", "purpose": "Effluent cooling"},
                    {"name": "HV-1113", "category": "Hand Valve", "purpose": "Bypass line manual isolation"},
                ]
            }
        })
    ])
    final = _turn(PID, "build complete feed station", "s10", graphs)
    sol = final.get("solution_design")
    assert sol is not None
    plan = sol.get("layout_plan")
    assert plan is not None
    assert len(plan) == 6
    
    corridors = {item["tag"]: item["corridor"] for item in plan}
    assert "Relief" in corridors["PSV-1111"]
    assert "Feed" in corridors["REACTOR-FEED-HDR"]
    assert "Feed" in corridors["M-116"]
    assert "Reaction" in corridors["R-110A"]
    assert "Separation" in corridors["HE-112"] or "Condensation" in corridors["HE-112"]
    assert "Effluent" in corridors["HV-1113"] or "Bypass" in corridors["HV-1113"]


def test_multi_turn_solution_accumulation(db, graphs, monkeypatch):
    """Verifies that subsequent design turns accumulate into the active solution."""
    # Turn 1: Add Reactor A feed
    _script_llm(monkeypatch, [
        json.dumps({
            "reply": "Added Reactor A Train.",
            "solution_design": {
                "inferred_plant_type": "Catalytic Reactor Train A",
                "unit_operations": ["Feed Ingress", "Catalytic Reaction A"],
                "component_roles": [
                    {"name": "M-116", "category": "Static Mixer", "purpose": "Feed component blending"},
                    {"name": "R-110A", "category": "Packed Bed Reactor", "purpose": "Catalytic reaction Stage A"},
                ],
                "layout_plan": [
                    {"tag": "M-116", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 0, "x": 100, "y": 260},
                    {"tag": "R-110A", "corridor": "Channel 3: Reaction Station", "row": 2, "col": 0, "x": 200, "y": 550},
                ],
                "optimizations": ["ISA-5.1 tag standardization"],
            }
        })
    ])
    turn1 = _turn(PID, "design reactor A train with M-116 and R-110A", "s_accum", graphs)
    sol1 = turn1.get("solution_design")
    assert sol1 is not None
    assert len(sol1["component_roles"]) == 2

    # Turn 2: Add Reactor B train (mirror)
    _script_llm(monkeypatch, [
        json.dumps({
            "reply": "Added Reactor B Train Mirror.",
            "solution_design": {
                "inferred_plant_type": "Catalytic Reactor Train B",
                "unit_operations": ["Catalytic Reaction B", "Effluent Throttling"],
                "component_roles": [
                    {"name": "R-110B", "category": "Packed Bed Reactor", "purpose": "Catalytic reaction Stage B"},
                    {"name": "HV-1155", "category": "Hand Valve", "purpose": "Manual train isolation"},
                ],
                "layout_plan": [
                    {"tag": "R-110B", "corridor": "Channel 3: Reaction Station", "row": 2, "col": 0, "x": 200, "y": 550},
                    {"tag": "HV-1155", "corridor": "Channel 5: Effluent & Bypass", "row": 3, "col": 0, "x": 200, "y": 880},
                ],
                "optimizations": ["Redundant parallel train operation"],
            }
        })
    ])
    turn2 = _turn(PID, "design mirrored reactor B train with R-110B and HV-1155", "s_accum", graphs)
    sol2 = turn2.get("solution_design")
    assert sol2 is not None

    # Check that component roles accumulated all 4 components
    role_names = {r["name"] for r in sol2["component_roles"]}
    assert role_names == {"M-116", "R-110A", "R-110B", "HV-1155"}

    # Check that unit operations merged
    assert "Feed Ingress" in sol2["unit_operations"]
    assert "Catalytic Reaction B" in sol2["unit_operations"]

    # Check that layout plan stacked non-overlapping coordinates in Channel 3
    r_a = next(item for item in sol2["layout_plan"] if item["tag"] == "R-110A")
    r_b = next(item for item in sol2["layout_plan"] if item["tag"] == "R-110B")
    assert r_a["corridor"] == "Channel 3: Reaction Station"
    assert r_b["corridor"] == "Channel 3: Reaction Station"
    assert r_a["col"] != r_b["col"]  # Distinct column indices
    assert r_a["x"] != r_b["x"]      # Distinct X coordinates


def test_architecture_completeness_and_maturity_gate(db, graphs, monkeypatch):
    """Verifies that solution architecture tracks the 60% completeness threshold."""
    # Turn 1: Partial Feed Header (score ~20-35%, can_build_canvas = False)
    _script_llm(monkeypatch, [
        json.dumps({
            "reply": "Added Feed Header spine.",
            "solution_design": {
                "inferred_plant_type": "Feed Ingress Rail",
                "unit_operations": ["Feed Ingress & Blending"],
                "component_roles": [
                    {"name": "REACTOR-FEED-HDR", "category": "Process Header", "purpose": "Main feed line"},
                    {"name": "M-116", "category": "Static Mixer", "purpose": "Feed component blending"},
                ],
                "layout_plan": [
                    {"tag": "REACTOR-FEED-HDR", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 0, "x": 100, "y": 260},
                    {"tag": "M-116", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 1, "x": 280, "y": 260},
                ],
            }
        })
    ])
    turn1 = _turn(PID, "design feed header spine with M-116", "s_gate", graphs)
    sol1 = turn1.get("solution_design")
    assert sol1 is not None
    comp1 = sol1.get("completeness")
    assert comp1 is not None
    assert comp1["score"] < 60
    assert comp1["can_build_canvas"] is False
    assert comp1["status"] == "draft_in_progress"

    # Turn 2: Add Reactor Train A + Relief PSV + Exchanger + Controls (score >= 60%, can_build_canvas = True)
    _script_llm(monkeypatch, [
        json.dumps({
            "reply": "Expanded architecture with Reaction Train, Relief, and Controls.",
            "solution_design": {
                "inferred_plant_type": "Catalytic Reaction & Separation Plant",
                "unit_operations": ["Catalytic Reaction", "Safety Relief", "Effluent Cooling"],
                "component_roles": [
                    {"name": "R-110A", "category": "Packed Bed Reactor", "purpose": "Catalytic reaction Stage A"},
                    {"name": "PSV-1111", "category": "Safety Relief Valve", "purpose": "Overpressure protection"},
                    {"name": "HE-112", "category": "Heat Exchanger", "purpose": "Effluent cooling"},
                    {"name": "PIT-1101", "category": "Pressure Transmitter", "purpose": "Electronic pressure measurement"},
                ],
                "layout_plan": [
                    {"tag": "R-110A", "corridor": "Channel 3: Reaction Station", "row": 2, "col": 0, "x": 200, "y": 550},
                    {"tag": "PSV-1111", "corridor": "Channel 1: Relief & Vent Rail", "row": 0, "col": 0, "x": 100, "y": 100},
                    {"tag": "HE-112", "corridor": "Channel 4: Condensation & Separation", "row": 2, "col": 0, "x": 500, "y": 450},
                    {"tag": "PIT-1101", "corridor": "Channel 2: Sensing & Control Tap", "row": 1, "col": 0, "x": 150, "y": 320},
                ],
            }
        })
    ])
    turn2 = _turn(PID, "add reactor train A with R-110A, PSV-1111, HE-112, and PIT-1101", "s_gate", graphs)
    sol2 = turn2.get("solution_design")
    assert sol2 is not None
    comp2 = sol2.get("completeness")
    assert comp2 is not None
    assert comp2["score"] >= 60
    assert comp2["can_build_canvas"] is True
    assert comp2["status"] == "ready_for_canvas"


def test_greenfield_systems_decomposition_and_instrument_configuration(db, graphs, monkeypatch):
    """Verifies that Greenfield Agent synthesizes Systems/Subsystems decomposition
    and full 4-way instrument and accessory configurations (Rosemount 3051S, Fisher DVC6200, PNL-01)."""
    _script_llm(monkeypatch, [
        # Greenfield agent execution:
        json.dumps({
            "reply": "Synthesized Greenfield Feed & Reaction Unit with 4-Way loop architecture.",
            "solution_design": {
                "inferred_plant_type": "Clean-Sheet Catalytic Reaction Unit with Separation & Flare Header",
                "unit_operations": [
                    "1. Feed Ingress & Blending System",
                    "2. Catalytic Reaction Station",
                    "3. Overpressure Safety Relief System",
                    "4. Downstream Condensation & Separation",
                    "5. Effluent & Sampling Loop"
                ],
                "project_objective": "Clean-sheet synthesis of reactor train with 4-way instrumentation.",
                "design_overview": "Designed balanced equipment trains and 4-way loop topology.",
                "component_roles": [
                    {
                        "tag": "PT-101",
                        "name": "Feed Header Pressure Transmitter",
                        "category": "Pressure Transmitter",
                        "purpose": "Line pressure measurement and control loop input"
                    },
                    {
                        "tag": "MNF-101",
                        "name": "3-Valve Manifold",
                        "category": "3-Valve Coplanar Manifold",
                        "purpose": "Instrument isolation and zero calibration"
                    },
                    {
                        "tag": "PIC-101",
                        "name": "DCS Pressure Controller",
                        "category": "DCS Indicating Controller",
                        "purpose": "Feedback control computation in Cabinet PNL-01"
                    },
                    {
                        "tag": "POS-101",
                        "name": "Smart Valve Positioner",
                        "category": "Smart Valve Positioner",
                        "purpose": "Electro-pneumatic valve position modulation"
                    },
                    {
                        "tag": "PCV-101",
                        "name": "Feed Pressure Control Valve",
                        "category": "Control Valve",
                        "purpose": "Globe valve body on main feed line"
                    },
                ],
                "layout_plan": [
                    {"tag": "PT-101", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 0, "x": 150, "y": 320},
                    {"tag": "MNF-101", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 1, "x": 200, "y": 320},
                    {"tag": "PIC-101", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 2, "x": 250, "y": 320},
                    {"tag": "POS-101", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 3, "x": 300, "y": 320},
                    {"tag": "PCV-101", "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": 4, "x": 350, "y": 320},
                ]
            }
        })
    ])

    res = _turn(PID, "design a new greenfield catalytic reactor facility from scratch", "s_gf", graphs)
    assert res.get("reply") is not None
    sol = res.get("solution_design")
    assert sol is not None
    assert sol["inferred_plant_type"] == "Clean-Sheet Catalytic Reaction Unit with Separation & Flare Header"
    assert len(sol["unit_operations"]) == 5
    assert "1. Feed Ingress & Blending System" in sol["unit_operations"]

    # Specifications are never invented. This test used to assert that every
    # component role was filled with manufacturer/model/range data derived from
    # its tag prefix ("PT-" -> Emerson Rosemount 3051S, 0-16 bar). That data was
    # fabricated, so roles now carry an explicit status instead, and only real
    # inventory records or engineer-stated values populate specifications.
    roles = {r["tag"]: r for r in sol["component_roles"]}
    for tag in ("PT-101", "PCV-101"):
        assert tag in roles
        role = roles[tag]
        assert role["spec_status"] == "unspecified"
        assert "specifications" not in role
        assert "instrument_config" not in role


def test_add_nodes_persists_specifications_in_sqlite(db):
    """Verifies that R.add_nodes stores specifications and instrument_config into SQLite nodes.extra_json."""
    res = R.add_nodes(PID, [
        {
            "tag": "PT-101",
            "kind": "transmitter",
            "area": "AREA-100",
            "description": "Feed Header Pressure Transmitter",
            "specifications": {
                "tag_number": "PT-101",
                "manufacturer": "Emerson Rosemount",
                "model": "3051S Coplanar",
                "calibrated_range": "0.0 - 16.0 bar",
                "protocol": "4-20mA HART 7",
                "connected_system": "Cabinet PNL-01 / Slot 01",
            },
            "instrument_config": {
                "hart_identity": {
                    "equipment_category": "Pressure Transmitter",
                    "hart_tag": "PT-101",
                    "hart_long_tag": "FEED_HEADER_PRESSURE",
                },
                "pv_mapping": {
                    "primary_variable": "Pressure",
                    "urv": "16.0",
                    "lrv": "0.0",
                    "pv_units": "bar",
                }
            }
        }
    ])
    assert "Added 1 node" in res

    node = R.get_node(PID, "PT-101")
    assert node is not None
    assert node["tag"] == "PT-101"
    assert "extra_json" in node
    extra = json.loads(node["extra_json"])
    assert "specifications" in extra
    assert extra["specifications"]["manufacturer"] == "Emerson Rosemount"
    assert extra["specifications"]["model"] == "3051S Coplanar"
    assert extra["specifications"]["calibrated_range"] == "0.0 - 16.0 bar"
    assert "instrument_config" in extra
    assert extra["instrument_config"]["hart_identity"]["hart_long_tag"] == "FEED_HEADER_PRESSURE"







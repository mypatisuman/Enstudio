"""Brownfield retrofit: agent foundation, plant hierarchy and instrument packages.

Every test runs against a throwaway studio.db seeded to look like a DIGITISED
drawing: extracted nodes carry a source_id, normalised 0-1 coordinates and the
page metadata extraction stamps. The LLM is scripted, so no API key is needed.

Defects pinned here, each observed on a copy of a real digitised project:
  * new nodes were placed at x=140..770 on a sheet stored as 0..1
  * the prompt taught get_node(node_id) / get_loops(loop_number)
  * every node was stamped with invented manufacturer/model/range data
  * add_edges inserted the same connection again on every repeat
  * a re-extraction without --source-id deleted every authored row
  * no system/subsystem existed anywhere
  * the brownfield agent could not modify or delete existing plant
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from agents.describe import base as B  # noqa: E402
from agents.describe.agents import router as RT  # noqa: E402
from agents.describe.services import repository as R  # noqa: E402
from agents.describe.workflows import describe_workflow as S  # noqa: E402
from services import hierarchy as H  # noqa: E402
from services import placement as PL  # noqa: E402

PID = "bf"
PAGE = {"drawing": "PID-110", "page": 1, "page_w": 5100, "page_h": 2920}

# A small digitised run: header -> indicator -> vessel -> hand valve.
SEED_NODES = [
    ("n1", "C2H4-HDR", "equipment", "110", 0.20, 0.30),
    ("n2", "PI-1110", "indicator", "110", 0.265, 0.30),
    ("n3", "M-116", "vessel", "110", 0.35, 0.30),
    ("n4", "HV-1113", "hand_valve", "110", 0.45, 0.30),
]
SEED_EDGES = [("n1", "n2", "stream"), ("n2", "n3", "stream"), ("n3", "n4", "stream")]


@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    c = dbmod.get_db()
    c.execute("INSERT INTO projects (id, title) VALUES (?, ?)", (PID, "Brownfield"))
    for nid, label, kind, area, x, y in SEED_NODES:
        c.execute("INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y, "
                  "extra_json, source_id) VALUES (?,?,?,?,?,?,?,?,?,1)",
                  (nid, PID, kind, kind, label, area, x, y, json.dumps(PAGE)))
    for f, t, k in SEED_EDGES:
        c.execute("INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json, "
                  "source_id) VALUES (?,?,?,?,?,?,1)",
                  (PID, f, t, k, "", json.dumps({"drawing": "PID-110"})))
    yield dbmod
    dbmod.close_db()


@pytest.fixture()
def empty_db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "empty.db")
    dbmod.init_db()
    dbmod.get_db().execute("INSERT INTO projects (id, title) VALUES ('empty', 'E')")
    yield dbmod
    dbmod.close_db()


@pytest.fixture()
def graphs():
    cp = InMemorySaver()
    return {intent: builder(cp) for intent, builder in S._BUILDERS.items()}


def _node(tag):
    r = R._find_node(PID, tag)
    assert r is not None, f"{tag} missing"
    return {"id": r[0], "label": r[1], "kind": r[2], "area": r[4], "x": r[5],
            "y": r[6], "extra": json.loads(r[7] or "{}")}


def _edges_between(a, b):
    ra, rb = R._find_node(PID, a), R._find_node(PID, b)
    rows = R._db().execute(
        "SELECT kind FROM edges WHERE pid=? AND ((from_id=? AND to_id=?) OR "
        "(from_id=? AND to_id=?))", (PID, ra[0], rb[0], rb[0], ra[0])).fetchall()
    return [tuple(r) for r in rows]


def _edge_count():
    return R._db().execute("SELECT COUNT(*) FROM edges WHERE pid=?", (PID,)).fetchone()[0]


# ═════════════════════════════════════════════════════════════════════════════
# Placement
# ═════════════════════════════════════════════════════════════════════════════

def test_added_nodes_land_inside_the_normalised_drawing(db):
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"},
                      {"tag": "PIC-2041", "kind": "controller"}], near_tag="PI-1110")
    anchor = _node("PI-1110")
    for tag in ("PT-2041", "PIC-2041"):
        n = _node(tag)
        assert 0.0 <= n["x"] <= 1.0 and 0.0 <= n["y"] <= 1.0, (tag, n["x"], n["y"])
        assert math.hypot(n["x"] - anchor["x"], n["y"] - anchor["y"]) < 0.25


def test_new_nodes_do_not_overlap_existing_ones(db):
    R.add_nodes(PID, [{"tag": f"TI-30{i}", "kind": "indicator"} for i in range(6)],
                near_tag="PI-1110")
    pts = [(r[0], r[1]) for r in R._db().execute("SELECT x, y FROM nodes WHERE pid=?", (PID,))]
    assert len(set(pts)) == len(pts), "two nodes share a position"


def test_explicit_side_is_honoured():
    spot = PL.pick_free_spot((0.5, 0.5), [(0.5, 0.5)], PL.parse_direction("to the left"))
    assert spot[0] < 0.5


def test_pixel_space_projects_scale_offsets():
    space = PL.SheetSpace.detect([(1000.0, 800.0), (4000.0, 2500.0)])
    assert space.extent > 1000
    spot = PL.pick_free_spot((1000.0, 800.0), [(1000.0, 800.0)], None, space)
    assert spot[0] - 1000.0 > 50, "offset must scale with a pixel-space sheet"


def test_seed_spots_wrap_instead_of_piling_on_the_edge():
    occupied: list = []
    spots = []
    for i in range(25):
        s = PL.seed_spot(i, occupied)
        occupied.append(s)
        spots.append(s)
    assert len(set(spots)) == 25
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in spots)


def test_authored_nodes_inherit_drawing_and_page_from_the_anchor(db):
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], near_tag="PI-1110")
    extra = _node("PT-2041")["extra"]
    assert extra["drawing"] == "PID-110" and extra["page_w"] == 5100
    assert extra["origin"] == "authored"


# ═════════════════════════════════════════════════════════════════════════════
# Specifications: real data only
# ═════════════════════════════════════════════════════════════════════════════

def test_no_specifications_are_invented(db):
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], near_tag="PI-1110")
    extra = _node("PT-2041")["extra"]
    assert extra["spec_status"] == "unspecified"
    assert "specifications" not in extra and "instrument_config" not in extra


def test_engineer_stated_specifications_are_kept(db):
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter",
                       "specifications": {"calibrated_range": "0-10 bar"}}], near_tag="PI-1110")
    extra = _node("PT-2041")["extra"]
    assert extra["spec_status"] == "stated"
    assert extra["specifications"] == {"calibrated_range": "0-10 bar"}


def test_inventory_specifications_win_when_available(db, monkeypatch):
    import services.asset_specs as AS
    monkeypatch.setattr(AS, "_inventory_lookup",
                        lambda tag: {"specifications": {"model": "real"}, "asset_id": "AST-1"})
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], near_tag="PI-1110")
    extra = _node("PT-2041")["extra"]
    assert extra["spec_status"] == "asset_inventory"
    assert extra["specifications"] == {"model": "real"} and extra["asset_id"] == "AST-1"


def test_inventory_is_never_contacted_unless_enabled(db, monkeypatch):
    """Importing adapters.mongodb loads mongo.env with override=True, so an
    un-enabled inventory must not even be imported."""
    import services.asset_specs as AS
    monkeypatch.delenv("STUDIO_ASSET_INVENTORY", raising=False)
    monkeypatch.setattr(AS, "_inventory_down", False)
    assert H.inventory_enabled() is False
    calls = []
    monkeypatch.setitem(sys.modules, "adapters.mongodb",
                        type(sys)("adapters.mongodb"))
    sys.modules["adapters.mongodb"].fetch_asset_by_tag = lambda tag: calls.append(tag)
    assert AS.resolve("PT-1")["spec_status"] == "unspecified"
    assert calls == []


# ═════════════════════════════════════════════════════════════════════════════
# Duplicates and re-extraction survival
# ═════════════════════════════════════════════════════════════════════════════

def test_repeating_add_edges_never_duplicates(db):
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], near_tag="PI-1110")
    first = R.add_edges(PID, [{"from_tag": "PI-1110", "to_tag": "PT-2041", "kind": "impulse"}])
    before = _edge_count()
    second = R.add_edges(PID, [{"from_tag": "PI-1110", "to_tag": "PT-2041", "kind": "impulse"}])
    assert first.startswith("Added 1")
    assert second.startswith("NOOP") and _edge_count() == before


def test_duplicate_within_one_request_is_skipped(db):
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], near_tag="PI-1110")
    out = R.add_edges(PID, [{"from_tag": "PI-1110", "to_tag": "PT-2041", "kind": "impulse"}] * 2)
    assert out.startswith("Added 1") and "Skipped 1" in out


@pytest.mark.parametrize("source_id", [None, 1, 2])
def test_authored_rows_survive_any_re_extraction(db, source_id):
    """A re-extraction rewrites the whole project; authored rows must be
    carried forward whichever document id the run has, including none."""
    from extraction_cli.commands import _rows_from_other_sources
    from repositories.project_repository import _db_persist_espx
    R.add_instrument_package(PID, "pressure", "PI-1110")
    kept_nodes, kept_edges = _rows_from_other_sources(PID, source_id)
    run_nodes = [{"id": "n1", "label": "C2H4-HDR", "kind": "equipment", "x": 0.2, "y": 0.3,
                  **({"source_id": source_id} if source_id else {})}]
    _db_persist_espx(PID, {"nodes": kept_nodes + run_nodes, "edges": kept_edges,
                           "studio": {}, "meta": {}})
    for tag in ("PT-1111", "MNF-1111", "SYP-1111", "HV-1111A"):
        assert R._find_node(PID, tag) is not None, f"{tag} lost on re-extraction ({source_id})"


# ═════════════════════════════════════════════════════════════════════════════
# Plant hierarchy
# ═════════════════════════════════════════════════════════════════════════════

def test_create_subsystem_builds_the_path_idempotently(db):
    first = R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress",
                               area="AREA-100", unit="Unit 100", plant="Plant 2")
    second = R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress",
                                area="AREA-100", unit="Unit 100", plant="Plant 2")
    assert first == second
    tree = R.list_hierarchy(PID)
    levels = []
    node = tree["roots"][0]
    while node:
        levels.append(node["level"])
        node = node["children"][0] if node["children"] else None
    assert levels == ["plant", "unit", "area", "system", "subsystem"]


def test_nodes_are_assigned_to_a_named_subsystem(db):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    out = R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}],
                      near_tag="PI-1110", subsystem="Feed Supply Header")
    assert "assigned to Feed Supply Header" in out
    assert H.node_assignment(PID, "PT-2041")["system"] == "Hydrocarbon Ingress"
    contents = R.get_subsystem_contents(PID, "Feed Supply Header")
    assert {n["tag"] for n in contents["nodes"]} == {"PT-2041"}


def test_unknown_subsystem_names_the_candidates(db):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    out = R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], subsystem="Reflux")
    assert out.startswith("ERROR: no subsystem named 'Reflux'")
    assert "Feed Supply Header" in out
    assert R._find_node(PID, "PT-2041") is None, "nothing may be written on error"


def test_ambiguous_subsystem_asks_to_narrow(db):
    R.create_subsystem(PID, "Drains", "Reactor System")
    R.create_subsystem(PID, "Drains", "Flare System")
    out = R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], subsystem="Drains")
    assert out.startswith("ERROR: 'Drains' is ambiguous")
    ok = R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}],
                     subsystem="Drains", system="Flare System")
    assert "assigned to Drains" in ok
    assert H.node_assignment(PID, "PT-2041")["system"] == "Flare System"


def test_bootstrap_groups_digitised_nodes_by_area(db):
    out = R.sync_hierarchy(PID, source="areas")
    assert "assigned 4 node(s)" in out
    assert H.node_assignment(PID, "n2") == {"area": "110"}
    assert R.sync_hierarchy(PID, source="areas").startswith("Created 0")


def test_inventory_sync_imports_levels_and_assigns_tags(db):
    assets = [{"tag_number": "PI-1110", "location": {
        "site": "Houston", "plant": "Plant 2", "unit": "Unit 100", "area": "AREA-100",
        "system": "Hydrocarbon Ingress", "subsystem": "Feed Supply Header"}}]
    res = H.sync_from_inventory(PID, fetch=lambda **kw: assets)
    assert res["assigned_nodes"] == 1
    assert H.node_assignment(PID, "n2")["subsystem"] == "Feed Supply Header"


def test_deleting_a_node_drops_its_assignment(db):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], subsystem="Feed Supply Header")
    R.delete_nodes(PID, ["PT-2041"])
    assert R._db().execute("SELECT COUNT(*) FROM node_hierarchy WHERE pid=?",
                           (PID,)).fetchone()[0] == 0


def test_graph_summary_lists_plant_groups(db):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    summary = R.graph_summary(PID)
    assert "Feed Supply Header [subsystem]" in summary


# ═════════════════════════════════════════════════════════════════════════════
# Instrument packages, tag numbering, tie-ins
# ═════════════════════════════════════════════════════════════════════════════

def test_pressure_package_builds_the_accessory_stack(db):
    out = R.add_instrument_package(PID, "pressure", "PI-1110")
    assert out.startswith("Built pressure package, loop 1111"), out
    for tag in ("HV-1111A", "SYP-1111", "MNF-1111", "PT-1111"):
        n = _node(tag)
        assert 0 <= n["x"] <= 1 and n["extra"]["spec_status"] == "unspecified"
    for a, b in (("PI-1110", "HV-1111A"), ("HV-1111A", "SYP-1111"),
                 ("SYP-1111", "MNF-1111"), ("MNF-1111", "PT-1111")):
        assert _edges_between(a, b) == [("impulse",)], (a, b)


def test_control_package_puts_the_valve_inline_and_completes_the_loop(db):
    out = R.add_instrument_package(PID, "pressure", "PI-1110", with_control=True,
                                   valve_between=["M-116", "HV-1113"])
    assert "Warnings" not in out, out
    assert _edges_between("M-116", "HV-1113") == [], "old direct run must be split"
    assert _edges_between("M-116", "PCV-1111") == [("stream",)]
    assert _edges_between("PCV-1111", "HV-1113") == [("stream",)]
    for a, b, kind in (("PT-1111", "PIC-1111", "signal"), ("PIC-1111", "POS-1111", "signal"),
                       ("AFR-1111", "POS-1111", "pneumatic"), ("POS-1111", "ACT-1111", "pneumatic"),
                       ("ACT-1111", "PCV-1111", "pneumatic")):
        assert _edges_between(a, b) == [(kind,)], (a, b)
    loop = next(l for l in R.get_loops(PID) if l["loop_id"] == "PIC-1111")
    assert loop["status"] == "complete", loop


def test_control_package_without_a_line_warns(db):
    out = R.add_instrument_package(PID, "flow", "C2H4-HDR", with_control=True)
    assert "not inline yet" in out
    valve = re.search(r"(FCV-\d+)", out).group(1)
    assert R._find_node(PID, valve) is not None, "the valve is still created"
    assert _edges_between(valve, "ACT-" + valve.split("-")[1]) == [("pneumatic",)]


@pytest.mark.parametrize("package, expected", [
    ("temperature", {"TW", "TE", "TT"}),
    ("flow", {"FE", "HV", "MNF", "FT"}),
    ("level", {"HV", "MNF", "LT"}),
])
def test_every_package_builds(db, package, expected):
    out = R.add_instrument_package(PID, package, "M-116")
    assert out.startswith(f"Built {package} package"), out
    tags = re.findall(r"'([A-Z]+)-\d+[A-Z]?'", out)
    assert expected <= set(tags)


def test_repeating_a_package_with_its_series_is_a_noop(db):
    R.add_instrument_package(PID, "pressure", "PI-1110", tag_series="2041")
    edges = _edge_count()
    again = R.add_instrument_package(PID, "pressure", "PI-1110", tag_series="2041")
    assert again.startswith("NOOP") and _edge_count() == edges


def test_a_second_package_takes_the_next_free_loop(db):
    R.add_instrument_package(PID, "pressure", "PI-1110")
    out = R.add_instrument_package(PID, "pressure", "PI-1110")
    assert "loop 1112" in out


def test_package_subsystem_defaults_to_the_anchors_group(db):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    R.assign_to_subsystem(PID, ["PI-1110"], "Feed Supply Header")
    R.add_instrument_package(PID, "pressure", "PI-1110")
    assert H.node_assignment(PID, "PT-1111").get("subsystem") == "Feed Supply Header"


def test_unknown_package_and_anchor_are_rejected(db):
    assert R.add_instrument_package(PID, "vibration", "PI-1110").startswith("ERROR")
    assert R.add_instrument_package(PID, "pressure", "NOPE-1").startswith("ERROR")


def test_next_tag_follows_the_plant_numbering(db):
    assert R.next_tag(PID, "PI", "1110") == "PI-1110A"
    assert R.next_tag(PID, "HV") == "HV-1114"
    assert R.next_tag(PID, "PT", "2041") == "PT-2041"


def test_break_line_requires_an_existing_run(db):
    assert R.break_line(PID, "C2H4-HDR", "M-116", {"tag": "XV-1"}).startswith("ERROR")
    out = R.break_line(PID, "M-116", "HV-1113", {"tag": "XV-1", "kind": "hand_valve"})
    assert out.startswith("Inserted XV-1")
    assert _edges_between("M-116", "XV-1") == [("stream",)]


def test_reroute_edge_moves_one_end_and_updates_the_mirror(db):
    out = R.reroute_edge(PID, "M-116", "HV-1113", "C2H4-HDR")
    assert out.startswith("Rerouted"), out
    assert _edges_between("M-116", "HV-1113") == []
    assert _edges_between("M-116", "C2H4-HDR") == [("stream",)]


# ═════════════════════════════════════════════════════════════════════════════
# Tool signatures, routing, step budget
# ═════════════════════════════════════════════════════════════════════════════

def test_generated_catalog_uses_the_real_argument_names():
    from agents.describe.agents.brownfield_agent import TOOLS
    catalog = B.tool_catalog(TOOLS)
    assert "- get_node(tag)" in catalog
    assert "get_loops(status_filter=None)" in catalog
    assert "node_id" not in catalog.split("review_proposal")[0]
    assert "[writes, engineer must confirm]" in catalog


_PROMPT_TOOL_RE = re.compile(r"\b([a-z_]+)\(([^)]*)\)")


@pytest.mark.parametrize("agent", ["authoring", "brownfield", "deletion", "greenfield",
                                   "query", "solution", "update", "validation"])
def test_prompts_only_mention_real_tool_arguments(agent):
    import importlib
    import inspect
    mod = importlib.import_module(f"agents.describe.agents.{agent}_agent")
    prompt = (STUDIO / "agents" / "describe" / "prompts" / f"describe_{agent}.md").read_text(encoding="utf-8")
    for name, args in _PROMPT_TOOL_RE.findall(prompt):
        if name not in mod.TOOLS or not args.strip():
            continue
        params = set(inspect.signature(mod.TOOLS[name]["fn"]).parameters)
        for raw in args.split(","):
            arg = raw.strip().split("=")[0].strip()
            if arg and re.match(r"^[a-z_]+$", arg):
                assert arg in params, f"describe_{agent}.md teaches {name}({arg}) but the tool takes {sorted(params)}"


def test_subsystem_wording_on_a_digitised_drawing_routes_to_brownfield(db):
    intent, reason, _ = RT.route_message(
        PID, "Add a pressure transmitter with manifold and siphon to the feed subsystem",
        use_llm=False)
    assert intent == "brownfield", reason


def test_same_wording_on_an_empty_project_is_not_forced_to_brownfield(empty_db):
    intent, _, _ = RT.route_message(
        "empty", "Add a pressure transmitter with manifold and siphon to the feed subsystem",
        use_llm=False)
    assert intent == "solution"


def test_greenfield_requests_stay_greenfield_on_a_digitised_project(db):
    intent, _, _ = RT.route_message(PID, "Design a new unit from scratch", use_llm=False)
    assert intent == "greenfield"


# ═════════════════════════════════════════════════════════════════════════════
# End-to-end brownfield turns (scripted LLM, real agent graph and database)
# ═════════════════════════════════════════════════════════════════════════════

def _script(monkeypatch, responses, prompts=None):
    it = iter(responses)

    def fake(prompt):
        if prompts is not None:
            prompts.append(prompt)
        return json.dumps(next(it))

    monkeypatch.setattr(B, "llm_complete", fake)


def test_brownfield_turn_builds_a_control_loop_into_a_subsystem(db, graphs, monkeypatch):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    prompts: list[str] = []
    _script(monkeypatch, [
        {"thought": "groups", "tool": "list_hierarchy", "args": {}},
        {"thought": "tie-in", "tool": "get_node", "args": {"tag": "PI-1110"}},
        {"thought": "build", "tool": "add_instrument_package",
         "args": {"package": "pressure", "anchor_tag": "PI-1110", "with_control": True,
                  "valve_between": ["M-116", "HV-1113"], "subsystem": "Feed Supply Header"}},
        {"reply": "Built pressure control loop 1111 in Feed Supply Header."},
    ], prompts)
    final = S.run_describe_turn(PID, "Retrofit a pressure control loop at PI-1110 into the "
                                "Feed Supply Header subsystem", "s1", graphs=graphs,
                                use_llm_router=False)
    assert final["agent"] == "brownfield", final.get("reply")
    assert [op["tool"] for op in final["ops"]] == ["add_instrument_package"]
    assert H.node_assignment(PID, "PCV-1111")["subsystem"] == "Feed Supply Header"
    assert final["validation"]["incomplete_loops"] == []
    assert "- add_instrument_package(" in prompts[0], "tool catalog must reach the model"
    assert "get_node(node_id)" not in prompts[0]


def test_brownfield_step_budget_fits_a_real_retrofit(db, graphs, monkeypatch):
    reads = [{"thought": "inspect", "tool": "search_graph", "args": {"query": "1110"}}] * 12
    _script(monkeypatch, reads + [{"reply": "Inspected."}])
    final = S.run_describe_turn(PID, "Retrofit review of the existing line at PI-1110",
                                "s2", graphs=graphs, use_llm_router=False)
    assert final["reply"] == "Inspected.", final["reply"]


def test_brownfield_delete_pauses_for_confirmation_and_resumes(db, graphs, monkeypatch):
    R.add_nodes(PID, [{"tag": "XV-9", "kind": "hand_valve"}], near_tag="HV-1113")
    _script(monkeypatch, [
        {"thought": "remove", "tool": "delete_nodes", "args": {"tags": ["XV-9"], "reason": "asked"}},
        {"reply": "Removed XV-9."},
    ])
    # Worded without delete/remove so the rules router picks brownfield: this
    # exercises brownfield's OWN confirmed delete tool and the multi-agent resume.
    paused = S.run_describe_turn(PID, "Retrofit the existing line at HV-1113 and take XV-9 out",
                                 "s3", graphs=graphs, use_llm_router=False)
    assert "__interrupt__" in paused, paused.get("reply")
    assert R._find_node(PID, "XV-9") is not None, "nothing deleted before confirmation"
    resumed = S.resolve_describe_turn(PID, "s3", True, graphs=graphs)
    assert resumed["agent"] == "brownfield"
    assert R._find_node(PID, "XV-9") is None


def test_digitisation_status(db):
    R.add_nodes(PID, [{"tag": "PT-2041", "kind": "transmitter"}], near_tag="PI-1110")
    status = R.digitisation_status(PID)
    assert status["digitised"] is True
    assert status["extracted_nodes"] == 4 and status["authored_nodes"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# Digitise-then-retrofit flow
# ═════════════════════════════════════════════════════════════════════════════

def test_brownfield_refuses_an_undigitised_project_without_calling_the_model(
        empty_db, graphs, monkeypatch):
    def _no_model(prompt):
        raise AssertionError("the model must not be called for an empty project")
    monkeypatch.setattr(B, "llm_complete", _no_model)
    final = S.run_describe_turn("empty", "Retrofit a pressure loop onto the existing header",
                                "g1", graphs=graphs, use_llm_router=False)
    assert final["agent"] == "brownfield" and final["status"] == "not_digitised"
    assert "no digitised drawing" in final["reply"]


def test_orchestrated_request_extracts_once_then_retrofits(empty_db, tmp_path):
    import hashlib
    from agents.orchestrator.workflows.app_workflow import run_brownfield_request
    drawing = tmp_path / "pid.pdf"
    drawing.write_bytes(b"%PDF-fake-drawing")
    digest = hashlib.sha256(drawing.read_bytes()).hexdigest()
    extract_calls, describe_calls = [], []

    def fake_extractor(hub, pid, source_path, source_id=None):
        extract_calls.append(source_path)
        c = empty_db.get_db()
        c.execute("INSERT INTO nodes (id, pid, kind, label, x, y, extra_json, source_id) "
                  "VALUES ('n1', ?, 'indicator', 'PI-1', 0.5, 0.5, '{}', 1)", (pid,))
        c.execute("INSERT INTO sources (pid, filename, file_hash) VALUES (?, 'pid.pdf', ?)",
                  (pid, digest))
        return {"status": "complete", "verified_nodes": [{"id": "n1"}]}

    def fake_describer(pid, message, session_id):
        describe_calls.append(message)
        return {"agent": "brownfield", "reply": "done", "ops": []}

    payload = {"pid": "empty", "hub": str(tmp_path), "message": "Retrofit PI-1",
               "source_path": str(drawing), "source_id": 1}
    first = run_brownfield_request(payload, extractor=fake_extractor, describer=fake_describer)
    second = run_brownfield_request(payload, extractor=fake_extractor, describer=fake_describer)
    assert first["extraction"]["ran"] is True and first["result"]["reply"] == "done"
    assert second["extraction"]["ran"] is False, "same file must not be re-extracted"
    assert len(extract_calls) == 1 and len(describe_calls) == 2


def test_orchestrated_request_stops_when_extraction_fails(empty_db, tmp_path):
    from agents.orchestrator.workflows.app_workflow import run_brownfield_request
    drawing = tmp_path / "bad.pdf"
    drawing.write_bytes(b"x")
    out = run_brownfield_request(
        {"pid": "empty", "hub": str(tmp_path), "message": "Retrofit", "source_path": str(drawing)},
        extractor=lambda *a, **k: {"status": "failed", "error": "unreadable"},
        describer=lambda *a: pytest.fail("must not retrofit a failed extraction"))
    assert out["error"] == "unreadable"


def test_app_request_routes_brownfield_mode():
    import inspect
    from agents.orchestrator.workflows import app_workflow
    assert 'mode' in inspect.getsource(app_workflow.run_app_request)


# ═════════════════════════════════════════════════════════════════════════════
# Subsystem clarification (asked before the brownfield agent runs)
# ═════════════════════════════════════════════════════════════════════════════

from agents.describe.services import subsystem_gate as SG  # noqa: E402


@pytest.mark.parametrize("message, expected", [
    ("Add a loop into the Feed Supply Header subsystem of the Hydrocarbon Ingress system",
     {"subsystem": "Feed Supply Header", "system": "Hydrocarbon Ingress"}),
    ("Add a pressure transmitter to the feed subsystem", {"subsystem": "feed"}),
    ('Put PT-9 in subsystem named "Drains"', {"subsystem": "Drains"}),
    ("Retrofit review of the existing line at PI-1110", {}),
])
def test_named_groups_are_read_from_the_request(message, expected):
    assert SG.named_groups(message) == expected


def _no_model(monkeypatch):
    def boom(prompt):
        raise AssertionError("the agent must not run while the subsystem is unresolved")
    monkeypatch.setattr(B, "llm_complete", boom)


def test_ambiguous_subsystem_is_asked_then_the_choice_reaches_the_agent(db, graphs, monkeypatch):
    R.create_subsystem(PID, "Drains", "Reactor System")
    R.create_subsystem(PID, "Drains", "Flare System")
    _no_model(monkeypatch)
    asked = S.run_describe_turn(PID, "Add a pressure package at HV-1113 into the Drains subsystem",
                                "sg1", graphs=graphs, use_llm_router=False)
    assert asked["agent"] == "holistic" and asked["ops"] == []
    assert "Reactor System › Drains" in asked["reply"] and "Flare System › Drains" in asked["reply"]
    assert S._load_pending(PID, "sg1")["kind"] == "subsystem"

    prompts: list[str] = []
    _script(monkeypatch, [
        {"thought": "build", "tool": "add_instrument_package",
         "args": {"package": "pressure", "anchor_tag": "HV-1113",
                  "subsystem": "Drains", "system": "Flare System"}},
        {"reply": "Built."},
    ], prompts)
    choice = 2 if asked["reply"].index("Flare System") > asked["reply"].index("Reactor System") else 1
    done = S.run_describe_turn(PID, str(choice), "sg1", graphs=graphs, use_llm_router=False)
    assert done["agent"] == "brownfield", done.get("reply")
    assert 'subsystem="Drains", system="Flare System"' in prompts[0]
    assert S._load_pending(PID, "sg1") is None
    assert H.node_assignment(PID, "PT-1114")["system"] == "Flare System"


def test_missing_subsystem_is_asked_only_when_there_is_a_choice(db, graphs, monkeypatch):
    _script(monkeypatch, [{"reply": "Noted."}])
    no_groups = S.run_describe_turn(PID, "Add a pressure transmitter package near HV-1113",
                                    "sg2", graphs=graphs, use_llm_router=False)
    assert no_groups["agent"] == "brownfield", "nothing to choose from: no question"

    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    R.create_subsystem(PID, "Reflux", "Column System")
    _no_model(monkeypatch)
    asked = S.run_describe_turn(PID, "Add a pressure transmitter package near HV-1113",
                                "sg3", graphs=graphs, use_llm_router=False)
    assert asked["agent"] == "holistic" and "doesn't say which one" in asked["reply"]

    prompts: list[str] = []
    _script(monkeypatch, [{"reply": "Noted."}], prompts)
    done = S.run_describe_turn(PID, "Feed Supply Header", "sg3", graphs=graphs,
                               use_llm_router=False)
    assert done["agent"] == "brownfield"
    assert 'subsystem="Feed Supply Header", system="Hydrocarbon Ingress"' in prompts[0]


def test_no_question_when_the_anchor_already_sits_in_a_subsystem(db, graphs, monkeypatch):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    R.create_subsystem(PID, "Reflux", "Column System")
    R.assign_to_subsystem(PID, ["HV-1113"], "Reflux")
    _script(monkeypatch, [{"reply": "Noted."}])
    out = S.run_describe_turn(PID, "Add a pressure transmitter package near HV-1113",
                              "sg4", graphs=graphs, use_llm_router=False)
    assert out["agent"] == "brownfield"


def test_none_leaves_the_retrofit_unassigned(db, graphs, monkeypatch):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    _no_model(monkeypatch)
    S.run_describe_turn(PID, "Add a pressure transmitter package near HV-1113", "sg5",
                        graphs=graphs, use_llm_router=False)
    prompts: list[str] = []
    _script(monkeypatch, [{"reply": "Noted."}], prompts)
    done = S.run_describe_turn(PID, "none", "sg5", graphs=graphs, use_llm_router=False)
    assert done["agent"] == "brownfield"
    assert "leave the new equipment unassigned" in prompts[0]


def test_unclear_answers_are_bounded_then_proceed_unassigned(db, graphs, monkeypatch):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    _no_model(monkeypatch)
    S.run_describe_turn(PID, "Add a pressure transmitter package near HV-1113", "sg6",
                        graphs=graphs, use_llm_router=False)
    again = S.run_describe_turn(PID, "hmm, not sure", "sg6", graphs=graphs, use_llm_router=False)
    assert again["agent"] == "holistic" and "didn't catch" in again["reply"]
    _script(monkeypatch, [{"reply": "Noted."}])
    done = S.run_describe_turn(PID, "whichever", "sg6", graphs=graphs, use_llm_router=False)
    assert done["agent"] == "brownfield"
    assert "left unassigned" in done["reply"]


def test_a_different_request_abandons_the_question(db, graphs, monkeypatch):
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    _no_model(monkeypatch)
    S.run_describe_turn(PID, "Add a pressure transmitter package near HV-1113", "sg7",
                        graphs=graphs, use_llm_router=False)
    _script(monkeypatch, [{"reply": "HV-1113 connects to M-116."}])
    out = S.run_describe_turn(PID, "What is connected to HV-1113?", "sg7", graphs=graphs,
                              use_llm_router=False)
    assert out["agent"] == "query" and S._load_pending(PID, "sg7") is None


def test_answer_by_system_name_picks_the_right_duplicate():
    cands = [{"hierarchy_id": 1, "name": "Drains", "system": "Reactor System",
              "path": "Reactor System › Drains"},
             {"hierarchy_id": 2, "name": "Drains", "system": "Flare System",
              "path": "Flare System › Drains"}]
    assert SG.interpret("the one in the flare system", cands) == ("select", cands[1])
    longer = [{"hierarchy_id": 3, "name": "Feed", "system": "A", "path": "A › Feed"},
              {"hierarchy_id": 4, "name": "Feed Supply Header", "system": "A",
               "path": "A › Feed Supply Header"}]
    assert SG.interpret("Feed Supply Header", longer) == ("select", longer[1])
    assert SG.interpret("7", cands) == ("unclear", None)


def test_create_system_and_get_subsystem(db):
    assert R.create_system(PID, "Flare System", area="AREA-100").startswith("System ready")
    R.create_subsystem(PID, "Drains", "Flare System")
    R.create_subsystem(PID, "Drains", "Reactor System")
    R.assign_to_subsystem(PID, ["HV-1113"], "Drains", system="Flare System")
    one = R.get_subsystem(PID, "Drains", system="Flare System")
    assert one["found"] and one["path"]["area"] == "AREA-100" and one["nodes"] == 1
    both = R.get_subsystem(PID, "Drains")
    assert both["ambiguous"] and len(both["candidates"]) == 2
    system = R.get_subsystem(PID, "Flare System")
    assert system["level"] == "system" and {"name": "Drains", "level": "subsystem"} in system["children"]
    assert R.get_subsystem(PID, "Nope")["found"] is False


def test_nodes_drawn_in_the_desktop_app_do_not_count_as_digitised(empty_db):
    # serde_json writes compact JSON; this used to be counted as extracted.
    empty_db.get_db().execute(
        "INSERT INTO nodes (id, pid, kind, label, x, y, extra_json) VALUES "
        "('d1', 'empty', 'pump', 'P-1', 0.5, 0.5, '{\"drawing\":\"DESCRIBE\",\"origin\":\"authored\"}')")
    status = R.digitisation_status("empty")
    assert status["digitised"] is False and status["authored_nodes"] == 1

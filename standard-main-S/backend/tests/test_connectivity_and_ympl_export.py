"""Connectivity graph JSON (schema 2.0.0 / 2.1.0) and the single YMPL writer.

The project here is seeded the way a real extraction now leaves it: nodes with
normalised coordinates and pixel bboxes, edges tied to persisted line runs, and
the page raster size in geometry_pages. A brownfield retrofit is then applied
through the real repository tools, and every export must reflect it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

STUDIO = Path(__file__).resolve().parent.parent
REPO = STUDIO.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from adapters import connectivity_export as CX  # noqa: E402
from adapters import ympl_export as YX  # noqa: E402
from agents.describe.services import repository as R  # noqa: E402
from services import geometry_store as G  # noqa: E402

PID = "cx"
W, H = 2000, 1000
PAGE = {"drawing": "PID-1", "page": 1, "page_w": W, "page_h": H}


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    from adapters import db as dbmod
    monkeypatch.setenv("STUDIO_AUTO_EXPORT", "on")
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    c = dbmod.get_db()
    c.execute("INSERT INTO projects (id, title) VALUES (?, 'Connectivity')", (PID,))
    nodes = [
        # id, label, kind, x, y, bbox_px
        ("s1_n1", "FEED-HDR", "equipment", 0.10, 0.50, [150, 470, 250, 530]),
        ("s1_n2", "PI-1110", "indicator", 0.30, 0.50, [580, 480, 620, 520]),
        ("s1_n3", "M-116", "vessel", 0.50, 0.50, [940, 440, 1060, 560]),
        ("s1_n4", "HV-1113", "hand_valve", 0.70, 0.50, [1385, 485, 1415, 515]),
        ("s1_n5", "VENT-HDR", "equipment", 0.90, 0.50, [1750, 470, 1850, 530]),
        ("s1_gj_0", "s1_gj_0", "junction", 0.40, 0.50, None),
    ]
    for nid, label, kind, x, y, bbox in nodes:
        extra = dict(PAGE, **({"bbox_px": bbox} if bbox else {}))
        c.execute("INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y, extra_json, "
                  "source_id) VALUES (?,?,?,?,?,'110',?,?,?,1)",
                  (nid, PID, kind, kind, label, x, y, json.dumps(extra)))
    # Stored orientation of the vent run is REVERSED (vent -> valve): the
    # exporter must report it as backward flow, found from the feed inlet.
    edges = [("s1_n1", "s1_n2", ["s1_line_0"]), ("s1_n2", "s1_gj_0", ["s1_line_1"]),
             ("s1_gj_0", "s1_n3", ["s1_line_1"]), ("s1_n3", "s1_n4", ["s1_line_2"]),
             ("s1_n5", "s1_n4", ["s1_line_3"])]
    for f, t, lines in edges:
        c.execute("INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json, source_id) "
                  "VALUES (?,?,?,'stream','',?,1)", (PID, f, t, json.dumps({"line_ids": lines})))
    G.persist_pages(PID, 1, [{
        "page": 1, "width": W, "height": H,
        "lines": [
            {"id": "s1_line_0", "type": "process", "style": "solid", "points": [[250, 500], [580, 500]]},
            {"id": "s1_line_1", "type": "process", "style": "solid", "points": [[620, 500], [940, 500]]},
            {"id": "s1_line_2", "type": "process", "style": "solid", "points": [[1060, 500], [1385, 500]]},
            {"id": "s1_line_3", "type": "process", "style": "solid", "points": [[1415, 500], [1750, 500]]},
            {"id": "s1_line_9", "type": "signal", "style": "dashed",
             "points": [[100, 100], [100, 300], [400, 300]]},
        ],
        "junctions": [
            {"id": "s1_gj_0", "kind": "t_junction", "x": 800.0, "y": 500.0, "degree": 3},
            {"id": "s1_cx_0", "kind": "crossover", "x": 1200.0, "y": 300.0},
            {"id": "s1_os_0", "kind": "open_endpoint", "x": 400.0, "y": 300.0, "line_index": 9},
        ],
    }])
    yield tmp_path
    dbmod.close_db()


def _retrofit():
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    return R.add_instrument_package(PID, "pressure", "PI-1110", subsystem="Feed Supply Header",
                                    with_control=True, valve_between=["M-116", "HV-1113"])


# ── schema ───────────────────────────────────────────────────────────────────

def test_the_reference_fixture_validates_against_the_schema():
    doc = json.loads((REPO / "fixtures" / "connectivity_graph 18.json").read_text(encoding="utf-8"))
    assert CX.validate(doc) == []


@pytest.mark.parametrize("version", ["2.0.0", "2.1.0"])
def test_export_is_schema_valid(hub, version):
    _retrofit()
    doc = CX.build_connectivity_graph(PID, version)
    assert CX.validate(doc) == []
    md = doc["metadata"]
    assert md["schema_version"] == version
    assert md["node_count"] == len(doc["nodes"]) and md["edge_count"] == len(doc["edges"])
    assert md["line_count"] == len(doc["lines"])
    assert md["control_loops_count"] == len(doc["control_loops"])
    assert md["geometry"] == "available"


def test_unknown_schema_version_is_rejected(hub):
    with pytest.raises(ValueError):
        CX.build_connectivity_graph(PID, "3.0.0")


# ── nodes ────────────────────────────────────────────────────────────────────

def test_symbols_use_pixel_points_and_detector_bboxes(hub):
    nodes = CX.build_connectivity_graph(PID)["nodes"]
    assert nodes["PI-1110"]["point"] == [600.0, 500.0]
    assert nodes["PI-1110"]["bbox"] == [580.0, 480.0, 620.0, 520.0]
    assert nodes["PI-1110"]["type"] == "instrument"
    assert nodes["HV-1113"]["type"] == "valve"


def test_headers_are_boundaries_with_flow_direction(hub):
    nodes = CX.build_connectivity_graph(PID)["nodes"]
    assert nodes["FEED-HDR"]["type"] == "boundary" and nodes["FEED-HDR"]["flow_direction"] == "inlet"
    assert nodes["VENT-HDR"]["flow_direction"] == "outlet"


def test_junctions_use_the_reference_key_scheme(hub):
    nodes = CX.build_connectivity_graph(PID)["nodes"]
    assert nodes["JX_T_000"] == {"type": "t_junction", "point": [800.0, 500.0], "label": "T000"}
    assert nodes["CROSSOVER_000"]["type"] == "crossover"
    assert "s1_line_9_end_open" in nodes and nodes["s1_line_9_end_open"]["label"] == "Open End"


def test_authored_nodes_get_a_nominal_bbox_and_2_1_0_fields(hub):
    _retrofit()
    doc = CX.build_connectivity_graph(PID, "2.1.0")
    pt = doc["nodes"]["PT-1111"]
    assert len(pt["bbox"]) == 4
    assert pt["origin"] == "authored" and pt["spec_status"] == "unspecified"
    assert pt["subsystem"] == "Feed Supply Header" and pt["system"] == "Hydrocarbon Ingress"
    assert 0 <= pt["point"][0] <= W and 0 <= pt["point"][1] <= H, "authored node must sit on the page"


def test_2_0_0_carries_no_hierarchy_fields(hub):
    _retrofit()
    pt = CX.build_connectivity_graph(PID, "2.0.0")["nodes"]["PT-1111"]
    assert "subsystem" not in pt and "origin" not in pt


# ── edges and lines ──────────────────────────────────────────────────────────

def test_every_edge_references_real_nodes_and_lines(hub):
    _retrofit()
    doc = CX.build_connectivity_graph(PID)
    for e in doc["edges"]:
        assert e["from"] in doc["nodes"] and e["to"] in doc["nodes"], e
        assert e["line_id"] in doc["lines"], e


def test_extracted_edges_keep_their_drawn_line(hub):
    edges = CX.build_connectivity_graph(PID)["edges"]
    feed = next(e for e in edges if e["from"] == "FEED-HDR")
    assert feed["line_id"] == "s1_line_0"


def test_authored_connections_get_a_synthesised_line(hub):
    _retrofit()
    doc = CX.build_connectivity_graph(PID)
    edge = next(e for e in doc["edges"] if e["from"] == "PT-1111" and e["to"] == "PIC-1111")
    line = doc["lines"][edge["line_id"]]
    assert edge["line_id"].startswith("line_e") and line["type"] == "signal" and line["style"] == "dashed"


def test_flow_direction_is_propagated_from_the_inlet(hub):
    edges = CX.build_connectivity_graph(PID)["edges"]
    feed = next(e for e in edges if e["from"] == "FEED-HDR")
    assert feed["_logical"] == "forward" and feed["_source"] == "BFS(FEED-HDR)"
    assert feed["direction"] == "left_to_right"
    reversed_run = next(e for e in edges if e["from"] == "VENT-HDR")
    assert reversed_run["_logical"] == "backward", "stored vent->valve is drawn against the flow"
    assert reversed_run["direction"] == "left_to_right"


def test_junction_roles_follow_the_flow(hub):
    edges = CX.build_connectivity_graph(PID)["edges"]
    into = next(e for e in edges if e["to"] == "JX_T_000")
    out_of = next(e for e in edges if e["from"] == "JX_T_000")
    assert into["_jx_roles"] == {"JX_T_000": "incoming"}
    assert out_of["_jx_roles"] == {"JX_T_000": "outgoing"}


def test_polyline_direction_is_mixed(hub):
    lines = CX.build_connectivity_graph(PID)["lines"]
    assert lines["s1_line_9"]["direction"] == "mixed"


# ── control loops and signal paths ───────────────────────────────────────────

def test_retrofit_loop_appears_with_its_accessories(hub):
    _retrofit()
    doc = CX.build_connectivity_graph(PID)
    loop = doc["control_loops"]["P1111"]
    assert loop["loop_type"] == "Pressure" and loop["loop_id"] == "1111"
    assert loop["instruments"] == ["PIC-1111", "PT-1111"]
    components = {c["id"] for c in loop["connected_components"]}
    assert {"POS-1111", "ACT-1111", "PCV-1111", "AFR-1111"} <= components
    assert {"MNF-1111", "SYP-1111"} <= set(loop["connected_inline"])
    assert doc["nodes"]["PT-1111"]["control_loop"] == {
        "loop_type": "Pressure", "loop_id": "1111", "loop_name": "P1111"}


def test_retrofit_signal_chain_is_a_primary_path(hub):
    _retrofit()
    paths = CX.build_connectivity_graph(PID)["signal_paths"]
    chain = next(p for p in paths if p["chain"][0] == "PT-1111")
    assert chain["chain"] == ["PT-1111", "PIC-1111", "POS-1111", "ACT-1111", "PCV-1111"]
    assert chain["signal_role"] == "primary"
    assert chain["start_node"]["id"] == "PT-1111" and chain["end_node"]["type"] == "valve"


# ── degradation ──────────────────────────────────────────────────────────────

def test_projects_without_geometry_still_export_and_say_so(hub):
    from adapters.db import get_db
    for t in ("geometry_pages", "geometry_lines", "geometry_junctions"):
        get_db().execute(f"DELETE FROM {t} WHERE pid=?", (PID,))
    get_db().execute("UPDATE nodes SET extra_json='{}' WHERE pid=?", (PID,))
    doc = CX.build_connectivity_graph(PID)
    assert doc["metadata"]["geometry"] == "unavailable"
    assert CX.validate(doc) == []
    assert doc["nodes"]["PI-1110"]["point"] == [300.0, 500.0], "nominal 1000x1000 page"


# ── YMPL: one writer ─────────────────────────────────────────────────────────

def test_ympl_contains_the_retrofit_and_its_hierarchy(hub):
    _retrofit()
    doc = YX.build_ympl(PID)
    nodes = {n["id"]: n for n in doc["nodes"]}
    assert nodes["PCV-1111"]["subsystem"] == "Feed Supply Header"
    assert nodes["PT-1111"]["spec_status"] == "unspecified"
    assert "specifications" not in nodes["PT-1111"]
    assert any(e["from"] == "PT-1111" and e["to"] == "PIC-1111" for e in doc["edges"])
    assert "enable" in doc


def test_topology_only_matches_the_former_desktop_shape(hub):
    doc = YX.build_ympl(PID, topology_only=True)
    assert set(doc) == {"edges", "id", "meta", "nodes", "schema_version", "title"}
    assert doc["meta"] == {"confidence": "high", "mermaid": ""}
    assert set(doc["nodes"][0]) <= {"id", "area", "kind", "kind_detail", "label", "x", "y",
                                    "system", "subsystem"}


def test_flask_route_and_cli_write_identical_ympl(hub, monkeypatch):
    """Both surfaces now go through adapters/ympl_export.py."""
    _retrofit()
    via_writer = YX.render_ympl(PID)
    out = subprocess.run([sys.executable, str(STUDIO / "export_ympl_cli.py"), str(hub), PID,
                          "--stdout"], capture_output=True, text=True, cwd=STUDIO, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    strip = lambda text: {k: v for k, v in yaml.safe_load(text).items() if k != "meta"}  # noqa: E731
    assert strip(out.stdout) == strip(via_writer)
    from controllers import export_controller
    src = Path(export_controller.__file__).read_text(encoding="utf-8")
    assert "adapters.ympl_export import write_ympl" in src


def test_ympl_round_trips_through_the_sdk_parser(hub, tmp_path):
    sys.path.insert(0, str(REPO / "sdk"))
    from ympl_parser.io import read_ympl
    _retrofit()
    path = YX.write_ympl(PID, tmp_path)
    parsed = read_ympl(path)
    assert {n["id"] for n in parsed["nodes"]} >= {"PT-1111", "PCV-1111"}


# ── CLIs and auto-refresh ────────────────────────────────────────────────────

def test_connectivity_cli_writes_a_valid_file(hub):
    _retrofit()
    out = subprocess.run([sys.executable, str(STUDIO / "export_connectivity_cli.py"), str(hub),
                          PID, "--schema", "2.1.0"], capture_output=True, text=True,
                         cwd=STUDIO, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["success"] and result["validation_errors"] == 0
    doc = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert doc["nodes"]["PT-1111"]["subsystem"] == "Feed Supply Header"


def test_exports_refresh_after_a_brownfield_turn(hub, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from agents.describe import base as B
    from agents.describe.workflows import describe_workflow as S
    R.create_subsystem(PID, "Feed Supply Header", "Hydrocarbon Ingress")
    script = iter([
        {"tool": "add_instrument_package",
         "args": {"package": "pressure", "anchor_tag": "PI-1110", "subsystem": "Feed Supply Header"}},
        {"reply": "Built."},
    ])
    monkeypatch.setattr(B, "llm_complete", lambda prompt: json.dumps(next(script)))
    cp = InMemorySaver()
    graphs = {k: b(cp) for k, b in S._BUILDERS.items()}
    final = S.run_describe_turn(PID, "Retrofit a pressure transmitter at PI-1110 into the "
                                "Feed Supply Header subsystem", "x",
                                graphs=graphs, use_llm_router=False)
    written = final["exports"]["written"]
    assert set(written) == {"connectivity", "connectivity_2_1_0", "ympl"}, final["exports"]
    doc = json.loads(Path(written["connectivity_2_1_0"]).read_text(encoding="utf-8"))
    assert doc["nodes"]["PT-1111"]["subsystem"] == "Feed Supply Header"
    assert "PT-1111" in Path(written["ympl"]).read_text(encoding="utf-8")


def test_auto_export_can_be_disabled(hub, monkeypatch):
    from services.export_refresh import refresh_after_edit
    monkeypatch.setenv("STUDIO_AUTO_EXPORT", "off")
    assert refresh_after_edit(PID) == {"skipped": "auto export disabled"}


# ── flow direction rules, heat tracing, loop groups, spatial clusters ────────

def _add_node(nid, label, kind, x, y, bbox=None):
    from adapters import db as dbmod
    extra = dict(PAGE, **({"bbox_px": bbox} if bbox else {}))
    dbmod.get_db().execute(
        "INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y, extra_json, source_id) "
        "VALUES (?,?,?,?,?,'110',?,?,?,1)", (nid, PID, kind, kind, label, x, y, json.dumps(extra)))


def _add_edge(f, t, kind="stream", lines=None):
    from adapters import db as dbmod
    dbmod.get_db().execute(
        "INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json, source_id) "
        "VALUES (?,?,?,?,'',?,1)", (PID, f, t, kind, json.dumps({"line_ids": lines or []})))


def _persist_with(extra_lines):
    rows = G.load(PID)
    lines = [{k: ln[k] for k in ("id", "type", "style", "points")} for ln in rows["lines"]]
    junctions = [{k: v for k, v in j.items() if k not in ("source_id", "page")} for j in rows["junctions"]]
    G.persist_pages(PID, 1, [{"page": 1, "width": W, "height": H,
                              "lines": lines + extra_lines, "junctions": junctions}])


def _edge(doc, a, b):
    return next(e for e in doc["edges"] if {e["from"], e["to"]} == {a, b})


def test_an_arrow_on_the_run_decides_flow_before_reachability(hub):
    # Arrow on the M-116 -> HV-1113 run pointing back towards M-116.
    _persist_with([{"id": "s1_line_20", "type": "flow_arrow", "style": "arrow",
                    "points": [[1300, 500], [1200, 500]]}])
    doc = CX.build_connectivity_graph(PID)
    e = _edge(doc, "M-116", "HV-1113")
    assert e["_source"] == "arrow-preassign" and e["_logical"] == "backward"
    assert "s1_line_20" not in doc["lines"], "annotations are not pipe runs"
    assert _edge(doc, "FEED-HDR", "PI-1110")["_source"].startswith("BFS(")
    assert CX.validate(doc) == []


def test_an_arrow_across_the_run_is_ignored(hub):
    _persist_with([{"id": "s1_line_20", "type": "flow_arrow", "style": "arrow",
                    "points": [[1200, 560], [1200, 505]]}])
    assert _edge(CX.build_connectivity_graph(PID), "M-116", "HV-1113")["_source"] != "arrow-preassign"


def test_flow_propagates_through_nodes_an_inlet_cannot_reach(hub):
    _add_node("u1", "XV-1", "hand_valve", 0.20, 0.80)
    _add_node("u2", "XV-2", "hand_valve", 0.40, 0.80)
    _add_node("u3", "XV-3", "hand_valve", 0.60, 0.80)
    _add_edge("u1", "u2")
    _add_edge("u3", "u2")                                  # stored against the flow
    _persist_with([{"id": "s1_line_21", "type": "flow_arrow", "style": "arrow",
                    "points": [[550, 800], [650, 800]]}])
    doc = CX.build_connectivity_graph(PID)
    assert _edge(doc, "XV-1", "XV-2")["_source"] == "arrow-preassign"
    tail = _edge(doc, "XV-2", "XV-3")
    assert tail["_source"] == "propagation(XV-2)" and tail["_logical"] == "backward"


def test_undecidable_runs_fall_back_to_drawing_convention(hub):
    _add_node("y1", "XV-8", "hand_valve", 0.80, 0.90)
    _add_node("y2", "XV-9", "hand_valve", 0.70, 0.90)
    _add_edge("y1", "y2")                                  # drawn right to left
    e = _edge(CX.build_connectivity_graph(PID), "XV-8", "XV-9")
    assert e["_source"] == "geometric-fallback" and e["_logical"] == "backward"


def test_heat_tracing_is_keyed_by_the_item_it_runs_beside(hub):
    _persist_with([{"id": "s1_line_30", "type": "heat_trace", "style": "heat_trace",
                    "points": [[950, 570], [1050, 570]]}])
    doc = CX.build_connectivity_graph(PID)
    assert doc["electric_heat_trace"] == {"M-116": [{"points": [950.0, 570.0, 1050.0, 570.0]}]}
    assert doc["metadata"]["electric_heat_trace_count"] == 1
    assert "s1_line_30" not in doc["lines"]
    assert CX.validate(doc) == []


def test_loops_linked_by_a_signal_form_a_group(hub):
    _retrofit()
    R.add_nodes(PID, [{"tag": "TT-1200", "kind": "transmitter"},
                      {"tag": "TIC-1200", "kind": "controller"}], near_tag="M-116")
    R.add_edges(PID, [{"from_tag": "TT-1200", "to_tag": "TIC-1200", "kind": "signal"},
                      {"from_tag": "TIC-1200", "to_tag": "PIC-1111", "kind": "signal"}])
    doc = CX.build_connectivity_graph(PID)
    # P1110 joins too: the package's root valve sits on PI-1110's own tapping,
    # so the two pressure loops share it.
    assert doc["loop_groups"] == [{"group_id": "LG_001", "loops": ["P1110", "P1111", "T1200"],
                                   "links": ["shared_component", "signal"],
                                   "shared_components": ["HV-1111A"]}]
    assert doc["metadata"]["loop_groups_count"] == 1
    assert CX.validate(doc) == []


def test_symbols_drawn_close_together_form_a_spatial_cluster(hub):
    for i, x in enumerate((1200, 1240, 1280)):
        _add_node(f"c{i}", f"XV-5{i}", "hand_valve", x / W, 0.2, [x, 190, x + 30, 210])
    doc = CX.build_connectivity_graph(PID)
    assert doc["spatial_clusters"] == [{"members": ["XV-50", "XV-51", "XV-52"], "page": 1,
                                        "bbox": [1200.0, 190.0, 1310.0, 210.0],
                                        "centroid": [1255.0, 200.0], "cluster_id": "SC_001"}]
    assert doc["metadata"]["spatial_clusters_count"] == 1


def test_origin_comes_from_the_database_column(hub):
    _retrofit()
    doc = CX.build_connectivity_graph(PID, "2.1.0")
    assert doc["nodes"]["PT-1111"]["origin"] == "authored"
    assert doc["nodes"]["M-116"]["origin"] == "extracted"

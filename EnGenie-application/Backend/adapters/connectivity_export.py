"""
adapters/connectivity_export.py — the P&ID connectivity graph JSON export.

Produces the schema-2.0.0 document described by
`schemas/connectivity_graph_2_0_0.schema.json`, which was derived field by field
from `fixtures/connectivity_graph 18.json`. The generator that produced that
fixture (Engram-Main's connectivity.py) is not part of this repository, so this
is a rebuild against the documented shape, fed from this application's own
database:

  * nodes/edges           — the digitised graph, including every retrofit
  * geometry_*            — pages, pipe runs and junctions saved at extraction
  * node_hierarchy        — systems and subsystems (schema 2.1.0 only)

Sections
--------
nodes            dict keyed by node key. Symbols: type, point, label, bbox, plus
                 control_loop (instruments) and flow_direction (boundaries).
                 Junctions: JX_T_###, EP_SHARE_###, CROSSOVER_###, *_open.
edges            every stored connection, each tied to a line (drawn, or a
                 synthesised straight run for authored connections).
lines            dict keyed by line id; pixel polylines.
control_loops    ISA grouping by measured variable + loop number.
signal_paths     maximal chains along signal/pneumatic connections.
expansion_joints nodes of kind expansion_joint.
electric_heat_trace
                 heat-tracing segments from the flow-annotation pass, keyed by
                 the label of the item each one runs beside.
loop_groups      control loops tied together by a shared final element or a
                 signal connection between them (cascade, override, split range).
spatial_clusters symbols drawn close together on a page (bbox gap at most
                 1.5% of the page's longer side), three or more per cluster.

Flow direction (_logical / _source), first rule that decides wins:
  arrow-preassign      an arrowhead drawn on the connection's run
  BFS(root)            nearer to an inlet boundary means upstream
  propagation(node)    a node whose decided connections all flow in (or all
                       out) passes that flow on to its undecided ones
  geometric-fallback   drawing convention: left to right, then top to bottom
Signal connections keep their stored orientation (signal-orientation).

Coordinates are pixels in each page's extraction raster, the space the saved
geometry uses. Nodes are stored normalised 0-1 and converted with the page size
recorded in geometry_pages. Projects digitised before geometry was saved still
export, with a nominal page size, and say so in metadata.geometry.

Schema 2.1.0 is 2.0.0 plus additive per-node fields (id, kind, page, origin,
spec_status, system, subsystem, hierarchy) and metadata.project_id. No 2.0.0
field changes meaning between the two.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

SCHEMA_2_0 = "2.0.0"
SCHEMA_2_1 = "2.1.0"
SUPPORTED = (SCHEMA_2_0, SCHEMA_2_1)

NOMINAL_PAGE = (1000.0, 1000.0)

SIGNAL_KINDS = {"signal", "pneumatic", "electrical", "electric", "hydraulic", "data",
                "capillary", "software"}
IMPULSE_KINDS = {"impulse"}
JUNCTION_TYPES = {"t_junction", "endpoint_share", "crossover", "open_endpoint"}
ANNOTATION_TYPES = {"flow_arrow", "heat_trace"}
CLUSTER_GAP = 0.015          # of the page's longer side
CLUSTER_MIN = 3

_TYPE_BY_KIND: dict[str, str] = {}
for _t, _kinds in {
    "equipment": "vessel reactor heat_exchanger exchanger pump compressor column tank drum "
                 "equipment heater absorber package vendor_package mixer separator boiler "
                 "furnace fan blower turbine agitator cooler condenser",
    "valve": "hand_valve valve check_valve control_valve solenoid_valve ball_valve gate_valve "
             "globe_valve butterfly_valve plug_valve needle_valve three_way_valve shutdown_valve",
    "safety_valve": "relief_valve safety_valve psv prv rupture_disc pressure_relief_valve",
    "regulator": "regulator pressure_regulator back_pressure_regulator",
    "mechanical": "actuator positioner motor mechanical",
    "instrument": "indicator transmitter controller element switch alarm analyzer analyser "
                  "meter gauge recorder sensor",
    "inline_component": "siphon manifold thermowell filter strainer reducer fitting orifice "
                        "expansion_joint quick_connect sight_glass flame_arrestor trap nozzle spool",
    "boundary": "off_page_connector connector boundary tie_in header battery_limit",
}.items():
    for _k in _kinds.split():
        _TYPE_BY_KIND[_k] = _t

_BOUNDARY_LABEL = re.compile(r"(HDR|HEADER|OFF[- ]?PAGE|BATTERY LIMIT|TIE[- ]?IN)", re.I)
_INLET = re.compile(r"\b(feed|supply|inlet|in|from|suction|cws|source)\b", re.I)
_OUTLET = re.compile(r"\b(vent|flare|drain|out|outlet|return|product|effluent|cwr|discharge)\b", re.I)
_ISA = re.compile(r"^([A-Z])([A-Z]{0,4})[- ]?\s*0*(\d{1,6})\s*([A-Z]?)$")

VARIABLES = {
    "A": "Analytical", "B": "Burner", "C": "Conductivity", "D": "Density", "E": "Voltage",
    "F": "Flow", "H": "Hand", "I": "Current", "J": "Power", "K": "Time", "L": "Level",
    "M": "Moisture", "P": "Pressure", "Q": "Quantity", "R": "Radiation", "S": "Speed",
    "T": "Temperature", "U": "Multivariable", "V": "Vibration", "W": "Weight",
    "Y": "Event", "Z": "Position",
}

_HALF_SIZE = {"equipment": 55, "boundary": 60, "instrument": 22, "valve": 18,
              "safety_valve": 18, "regulator": 18, "mechanical": 18, "inline_component": 16}


def _db():
    from adapters.db import get_db
    return get_db()


def node_type(kind: str | None, label: str | None, category: str | None = None) -> str:
    """Map a stored node kind onto the schema's node-type vocabulary."""
    k = (kind or "").strip().lower()
    if k in ("junction", "tee", "t_junction"):
        return "t_junction"
    t = _TYPE_BY_KIND.get(k)
    if t is None and (category or "").lower() == "instrument":
        t = "instrument"
    if t in (None, "equipment") and _BOUNDARY_LABEL.search(label or ""):
        return "boundary"
    return t or "inline_component"


def _direction(start, end) -> str:
    dx, dy = end[0] - start[0], end[1] - start[1]
    if abs(dx) >= abs(dy):
        return "left_to_right" if dx >= 0 else "right_to_left"
    return "top_to_bottom" if dy >= 0 else "bottom_to_top"


def _line_direction(points: list) -> str:
    if len(points) < 2:
        return "unknown"
    xs = {round(p[0], 1) for p in points}
    ys = {round(p[1], 1) for p in points}
    if len(points) > 2 and len(xs) > 1 and len(ys) > 1:
        return "mixed"
    if points[0] == points[-1]:
        return "unknown"
    return _direction(points[0], points[-1])


def _extra(raw) -> dict:
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def _is_controller(label: str) -> bool:
    """ISA controller functions carry a C (PIC, TC, FIC, LIC ...)."""
    m = _ISA.match(label or "")
    return bool(m and "C" in (m.group(2) or ""))


def _round(v: float) -> float:
    return round(float(v), 1)


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _seg_project(p, a, b) -> tuple[float, float]:
    """(distance from p to segment ab, unclamped position t along ab)."""
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.dist(p, a), 0.0
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2
    tc = max(0.0, min(1.0, t))
    return math.dist(p, (ax + tc * dx, ay + tc * dy)), t


def _edge_polyline(edge: dict, geo_lines: dict, pa, pb) -> list:
    """The drawn run behind an edge, ordered from its `from` end to its `to`
    end; a straight segment when no run is recorded."""
    for lid in edge["extra"].get("line_ids") or []:
        ln = geo_lines.get(lid)
        if ln and ln.get("type") not in ANNOTATION_TYPES and len(ln.get("points") or []) >= 2:
            pts = ln["points"]
            if math.dist(pts[0], pa) + math.dist(pts[-1], pb) > math.dist(pts[0], pb) + math.dist(pts[-1], pa):
                pts = list(reversed(pts))
            return pts
    return [pa, pb]


def _arrow_vote(poly: list, arrows: list, dims) -> int:
    """Sum of +1 (arrow points from->to) / -1 (to->from) over arrowheads that
    sit on the run and lie along it. 0 when none, or when they disagree evenly."""
    tol = max(12.0, 0.008 * max(dims))
    vote = 0
    for tail, tip in arrows:
        vx, vy = tip[0] - tail[0], tip[1] - tail[1]
        vlen = math.hypot(vx, vy)
        if vlen == 0:
            continue
        best = None
        for a, b in zip(poly, poly[1:]):
            d, t = _seg_project(tip, a, b)
            if d <= tol and -0.05 <= t <= 1.05 and (best is None or d < best[0]):
                best = (d, a, b)
        if best is None:
            continue
        _, a, b = best
        sx, sy = b[0] - a[0], b[1] - a[1]
        slen = math.hypot(sx, sy)
        if slen == 0:
            continue
        cos = (vx * sx + vy * sy) / (vlen * slen)
        if abs(cos) >= 0.7:
            vote += 1 if cos > 0 else -1
    return vote


def _bbox_gap(p, q) -> float:
    dx = max(0.0, max(p[0], q[0]) - min(p[2], q[2]))
    dy = max(0.0, max(p[1], q[1]) - min(p[3], q[3]))
    return math.hypot(dx, dy)


def spatial_clusters(items: list) -> list[dict]:
    """Single-link grouping of symbol boxes per page.

    items: (key, bbox, page_key, page_dims). Two symbols join when the gap
    between their boxes is at most CLUSTER_GAP of the page's longer side.
    Plain geometry: no learned model, no randomness, same input -> same output.
    """
    by_page: dict[tuple, list] = defaultdict(list)
    for item in items:
        by_page[item[2]].append(item)
    clusters = []
    for page_key in sorted(by_page):
        group = by_page[page_key]
        parent = list(range(len(group)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(group)):
            limit = CLUSTER_GAP * max(group[i][3])
            for j in range(i + 1, len(group)):
                if _bbox_gap(group[i][1], group[j][1]) <= limit:
                    parent[find(i)] = find(j)
        members: dict[int, list] = defaultdict(list)
        for i, item in enumerate(group):
            members[find(i)].append(item)
        for found in members.values():
            if len(found) < CLUSTER_MIN:
                continue
            boxes = [m[1] for m in found]
            box = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                   max(b[2] for b in boxes), max(b[3] for b in boxes)]
            clusters.append({"members": sorted(m[0] for m in found), "page": page_key[1],
                             "bbox": [_round(v) for v in box],
                             "centroid": [_round((box[0] + box[2]) / 2), _round((box[1] + box[3]) / 2)]})
    clusters.sort(key=lambda c: (c["page"], c["bbox"][1], c["bbox"][0]))
    for n, c in enumerate(clusters, 1):
        c["cluster_id"] = f"SC_{n:03d}"
    return clusters


# ── Loading ──────────────────────────────────────────────────────────────────

def _load(pid: str) -> dict[str, Any]:
    db = _db()
    try:
        origin_col = ", origin"
        db.execute("SELECT origin FROM nodes LIMIT 0")
    except Exception:                               # hub not migrated yet
        origin_col = ", NULL"
    nodes = [{"id": r[0], "kind": r[1], "kind_detail": r[2], "label": r[3], "area": r[4],
              "x": r[5], "y": r[6], "extra": _extra(r[7]), "source_id": r[8],
              "origin": r[9] or _extra(r[7]).get("origin") or "extracted"}
             for r in db.execute("SELECT id, kind, kind_detail, label, area, x, y, extra_json, "
                                 f"source_id{origin_col} FROM nodes WHERE pid=? ORDER BY rowid",
                                 (pid,)).fetchall()]
    edges = [{"rowid": r[0], "from": r[1], "to": r[2], "kind": (r[3] or "stream").lower(),
              "extra": _extra(r[4]), "origin": r[5] or _extra(r[4]).get("origin") or "extracted"}
             for r in db.execute(f"SELECT id, from_id, to_id, kind, extra_json{origin_col} FROM edges "
                                 "WHERE pid=? ORDER BY id", (pid,)).fetchall()]
    try:
        from services.geometry_store import load as load_geometry
        geometry = load_geometry(pid)
    except Exception:
        geometry = {"pages": {}, "lines": [], "junctions": []}
    try:
        from services.hierarchy import assignments
        hierarchy = assignments(pid)
    except Exception:
        hierarchy = {}
    return {"nodes": nodes, "edges": edges, "geometry": geometry, "hierarchy": hierarchy}


# ── Coordinates ──────────────────────────────────────────────────────────────

class _Pages:
    def __init__(self, pages: dict):
        self.pages = pages
        self.nominal_used = False

    def dims(self, node: dict) -> tuple[float, float]:
        extra = node["extra"]
        page = int(extra.get("page") or 1)
        sid = int(node.get("source_id") or extra.get("anchor_source_id") or 0)
        found = self.pages.get((sid, page))
        if found is None and len(self.pages) == 1:
            found = next(iter(self.pages.values()))
        if found and found.get("width") and found.get("height"):
            return float(found["width"]), float(found["height"])
        if extra.get("bbox_page_w") and extra.get("bbox_page_h"):
            return float(extra["bbox_page_w"]), float(extra["bbox_page_h"])
        if extra.get("page_w") and extra.get("page_h"):
            return float(extra["page_w"]), float(extra["page_h"])
        self.nominal_used = True
        return NOMINAL_PAGE

    def point(self, node: dict) -> list[float]:
        x, y = float(node.get("x") or 0), float(node.get("y") or 0)
        if max(abs(x), abs(y)) > 1.5:                  # already pixel space
            return [_round(x), _round(y)]
        w, h = self.dims(node)
        return [_round(x * w), _round(y * h)]


# ── Export ───────────────────────────────────────────────────────────────────

def build_connectivity_graph(pid: str, schema_version: str = SCHEMA_2_0) -> dict:
    if schema_version not in SUPPORTED:
        raise ValueError(f"unsupported schema_version {schema_version!r}; use one of {SUPPORTED}")
    extended = schema_version == SCHEMA_2_1
    data = _load(pid)
    pages = _Pages(data["geometry"]["pages"])
    geo_lines = {ln["id"]: ln for ln in data["geometry"]["lines"]}
    geo_junctions = {j["id"]: j for j in data["geometry"]["junctions"]}

    # ── node keys ────────────────────────────────────────────────────────────
    label_counts = Counter((n["label"] or "").strip() for n in data["nodes"])
    counters: Counter = Counter()
    key_of: dict[str, str] = {}
    out_nodes: dict[str, dict] = {}
    meta_of: dict[str, dict] = {}                    # key -> internal facts

    def _junction_key(kind: str, line_ref: str | None = None) -> tuple[str, str]:
        n = counters[kind]
        counters[kind] += 1
        if kind == "t_junction":
            return f"JX_T_{n:03d}", f"T{n:03d}"
        if kind == "endpoint_share":
            return f"EP_SHARE_{n:03d}", f"EP{n}"
        if kind == "crossover":
            return f"CROSSOVER_{n:03d}", f"XO{n}"
        return (f"{line_ref}_end_open" if line_ref else f"OPEN_{n:03d}"), "Open End"

    for node in data["nodes"]:
        label = (node["label"] or "").strip()
        ntype = node_type(node["kind"], label, node["extra"].get("category"))
        geo_j = geo_junctions.get(node["id"])
        if geo_j is not None or ntype == "t_junction":
            ntype = (geo_j or {}).get("kind") or "t_junction"
            key, jlabel = _junction_key(ntype)
            point = ([_round(geo_j["x"]), _round(geo_j["y"])] if geo_j else pages.point(node))
            entry = {"type": ntype, "point": point, "label": jlabel}
        else:
            key = label if label and label_counts[label] == 1 and label not in out_nodes else node["id"]
            point = pages.point(node)
            entry = {"type": ntype, "point": point, "label": label or node["id"]}
            bbox = node["extra"].get("bbox_px")
            if bbox and len(bbox) == 4:
                entry["bbox"] = [_round(v) for v in bbox]
            else:
                half = _HALF_SIZE.get(ntype, 16)
                entry["bbox"] = [_round(point[0] - half), _round(point[1] - half),
                                 _round(point[0] + half), _round(point[1] + half)]
        if extended:
            path = data["hierarchy"].get(node["id"], {})
            entry.update({"id": node["id"], "kind": node["kind"] or "",
                          "page": int(node["extra"].get("page") or 1),
                          "origin": node["origin"],
                          "spec_status": node["extra"].get("spec_status"),
                          "system": path.get("system"), "subsystem": path.get("subsystem"),
                          "hierarchy": path})
        key_of[node["id"]] = key
        out_nodes[key] = entry
        meta_of[key] = {"db_id": node["id"], "kind": (node["kind"] or "").lower(),
                        "kind_detail": node["kind_detail"] or node["kind"] or "",
                        "page": (int(node.get("source_id") or node["extra"].get("anchor_source_id") or 0),
                                 int(node["extra"].get("page") or 1)),
                        "dims": pages.dims(node)}

    used_geo = set(key_of)
    for jid, j in geo_junctions.items():
        if jid in used_geo:
            continue
        line_ref = None
        if j.get("kind") == "open_endpoint" and j.get("line_index") is not None:
            prefix = jid.rsplit("os_", 1)[0]
            line_ref = f"{prefix}line_{j['line_index']}"
        key, jlabel = _junction_key(j.get("kind") or "t_junction", line_ref)
        out_nodes[key] = {"type": j.get("kind") or "t_junction",
                          "point": [_round(j["x"]), _round(j["y"])], "label": jlabel}
        meta_of[key] = {"db_id": jid, "kind": "junction", "kind_detail": j.get("kind"),
                        "page": (int(j.get("source_id") or 0), int(j.get("page") or 1)),
                        "dims": None}

    # ── adjacency ────────────────────────────────────────────────────────────
    edges = [e for e in data["edges"] if e["from"] in key_of and e["to"] in key_of]
    process_adj: dict[str, set] = defaultdict(set)
    any_adj: dict[str, list] = defaultdict(list)
    for e in edges:
        a, b = key_of[e["from"]], key_of[e["to"]]
        any_adj[a].append((b, e["kind"]))
        any_adj[b].append((a, e["kind"]))
        if e["kind"] not in SIGNAL_KINDS and e["kind"] not in IMPULSE_KINDS:
            process_adj[a].add(b)
            process_adj[b].add(a)

    # ── boundaries: inlet / outlet ───────────────────────────────────────────
    out_deg, in_deg = Counter(), Counter()
    for e in edges:
        if e["kind"] not in SIGNAL_KINDS:
            out_deg[key_of[e["from"]]] += 1
            in_deg[key_of[e["to"]]] += 1
    for key, entry in out_nodes.items():
        if entry["type"] != "boundary":
            continue
        label = entry["label"]
        if _OUTLET.search(label.replace("-", " ").replace("_", " ")):
            entry["flow_direction"] = "outlet"
        elif _INLET.search(label.replace("-", " ").replace("_", " ")):
            entry["flow_direction"] = "inlet"
        else:
            entry["flow_direction"] = "inlet" if out_deg[key] >= in_deg[key] else "outlet"

    # ── flow direction: multi-source BFS from inlets ─────────────────────────
    roots = [k for k, v in out_nodes.items() if v.get("flow_direction") == "inlet"]
    if not roots:
        roots = [k for k in process_adj if in_deg[k] == 0] or list(process_adj)[:1]
    dist: dict[str, int] = {}
    root_of: dict[str, str] = {}
    queue = deque()
    for r in roots:
        dist[r], root_of[r] = 0, r
        queue.append(r)
    while queue:
        cur = queue.popleft()
        for nxt in process_adj[cur]:
            if nxt not in dist:
                dist[nxt], root_of[nxt] = dist[cur] + 1, root_of[cur]
                queue.append(nxt)

    # ── lines + edges ────────────────────────────────────────────────────────
    out_lines: dict[str, dict] = {}
    for lid, ln in geo_lines.items():
        pts = [[_round(p[0]), _round(p[1])] for p in ln.get("points") or []]
        if len(pts) < 2 or ln.get("type") in ANNOTATION_TYPES:
            continue
        out_lines[lid] = {"id": lid, "type": "signal" if ln.get("type") == "signal" else "process",
                          "points": pts, "style": "dashed" if ln.get("style") == "dashed" else "solid",
                          "direction": _line_direction(pts)}

    # ── flow direction ───────────────────────────────────────────────────────
    decided: dict[int, tuple[str, str]] = {}          # edge index -> (_logical, _source)
    is_signal = [e["kind"] in SIGNAL_KINDS or e["kind"] in IMPULSE_KINDS for e in edges]
    for i, e in enumerate(edges):
        if is_signal[i]:
            decided[i] = ("forward", "signal-orientation")

    # 1. arrowheads drawn on the run
    arrows: dict[tuple, list] = defaultdict(list)
    for ln in geo_lines.values():
        if ln.get("type") == "flow_arrow" and len(ln.get("points") or []) == 2:
            arrows[(int(ln.get("source_id") or 0), int(ln.get("page") or 1))].append(ln["points"])
    all_arrows = [a for group in arrows.values() for a in group]
    one_page = len({k for k in arrows} | set(data["geometry"]["pages"])) <= 1
    for i, e in enumerate(edges):
        if i in decided or not all_arrows:
            continue
        a, b = key_of[e["from"]], key_of[e["to"]]
        candidates = all_arrows if one_page else arrows.get(meta_of[a]["page"], [])
        vote = _arrow_vote(_edge_polyline(e, geo_lines, out_nodes[a]["point"], out_nodes[b]["point"]),
                           candidates, meta_of[a]["dims"] or NOMINAL_PAGE)
        if vote:
            decided[i] = ("forward" if vote > 0 else "backward", "arrow-preassign")

    # 2. reachability from inlets
    for i, e in enumerate(edges):
        if i in decided:
            continue
        a, b = key_of[e["from"]], key_of[e["to"]]
        if a in dist and b in dist and dist[a] != dist[b]:
            upstream = a if dist[a] < dist[b] else b
            decided[i] = ("forward" if upstream == a else "backward", f"BFS({root_of[upstream]})")

    # 3. propagation through nodes whose decided connections agree
    def _flow(i: int) -> tuple[str, str]:                 # (upstream key, downstream key)
        a, b = key_of[edges[i]["from"]], key_of[edges[i]["to"]]
        return (a, b) if decided[i][0] == "forward" else (b, a)

    touching: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(edges):
        if not is_signal[i]:
            touching[key_of[e["from"]]].append(i)
            touching[key_of[e["to"]]].append(i)
    changed = True
    while changed:
        changed = False
        for key, idxs in touching.items():
            open_ = [i for i in idxs if i not in decided]
            if not open_:
                continue
            ins = sum(1 for i in idxs if i in decided and _flow(i)[1] == key)
            outs = sum(1 for i in idxs if i in decided and _flow(i)[0] == key)
            role = out_nodes[key].get("flow_direction")
            if ins and not outs and role != "outlet":
                leaving = True
            elif outs and not ins and role != "inlet":
                leaving = False
            else:
                continue
            for i in open_:
                a = key_of[edges[i]["from"]]
                forward = (a == key) == leaving
                decided[i] = ("forward" if forward else "backward", f"propagation({key})")
            changed = True

    # 4. drawing convention
    for i, e in enumerate(edges):
        if i not in decided:
            pa, pb = out_nodes[key_of[e["from"]]]["point"], out_nodes[key_of[e["to"]]]["point"]
            dx, dy = pb[0] - pa[0], pb[1] - pa[1]
            forward = dx >= 0 if abs(dx) >= abs(dy) else dy >= 0
            decided[i] = ("forward" if forward else "backward", "geometric-fallback")

    out_edges = []
    for i, e in enumerate(edges):
        a, b = key_of[e["from"]], key_of[e["to"]]
        pa, pb = out_nodes[a]["point"], out_nodes[b]["point"]
        logical, source = decided[i]
        start, end = (a, b) if logical == "forward" else (b, a)
        line_id = next((lid for lid in e["extra"].get("line_ids") or [] if lid in out_lines), None)
        if line_id is None:
            line_id = f"line_e{e['rowid']}"
            sig = e["kind"] in SIGNAL_KINDS
            out_lines[line_id] = {"id": line_id, "type": "signal" if sig else "process",
                                  "points": [list(pa), list(pb)],
                                  "style": "dashed" if sig else "solid",
                                  "direction": _line_direction([pa, pb])}
        roles = {}
        for k, role in ((start, "outgoing"), (end, "incoming")):
            if out_nodes[k]["type"] in JUNCTION_TYPES:
                roles[k] = role
        out_edges.append({
            "id": f"E_{i:04d}", "from": a, "to": b, "line_id": line_id,
            "direction": _direction(out_nodes[start]["point"], out_nodes[end]["point"]),
            "is_expansion_joint": "expansion_joint" in (meta_of[a]["kind"], meta_of[b]["kind"]),
            "_logical": logical, "_source": source, "_jx_roles": roles,
        })
        if extended:
            out_edges[-1]["kind"] = e["kind"]
            out_edges[-1]["origin"] = e["origin"]

    # ── control loops ────────────────────────────────────────────────────────
    loops: dict[str, dict] = {}
    for key, entry in out_nodes.items():
        m = _ISA.match(entry["label"]) if entry["type"] in ("instrument", "valve", "regulator") else None
        if not m or m.group(1) not in VARIABLES:
            continue
        if entry["type"] != "instrument":
            continue
        name = f"{m.group(1)}{m.group(3)}"
        loop = loops.setdefault(name, {"loop_type": VARIABLES[m.group(1)], "loop_id": m.group(3),
                                       "instruments": [], "connected_components": [],
                                       "process_line_junctions": {}, "connected_inline": []})
        loop["instruments"].append(entry["label"])
        entry["control_loop"] = {"loop_type": loop["loop_type"], "loop_id": loop["loop_id"],
                                 "loop_name": name}

    expandable = {"inline_component", "mechanical", "regulator"}
    for name, loop in loops.items():
        members = {k for k, v in out_nodes.items() if v.get("control_loop", {}).get("loop_name") == name}
        components, inline = {}, []
        seen = set(members)
        frontier = deque((k, 0) for k in members)
        while frontier:
            cur, depth = frontier.popleft()
            for nxt, kind in any_adj[cur]:
                ntype = out_nodes[nxt]["type"]
                if ntype in JUNCTION_TYPES and cur in members:
                    pj = loop["process_line_junctions"].setdefault(
                        nxt, {"point": out_nodes[nxt]["point"], "via_instruments": []})
                    if out_nodes[cur]["label"] not in pj["via_instruments"]:
                        pj["via_instruments"].append(out_nodes[cur]["label"])
                if nxt in seen or ntype in ("instrument", "boundary") or ntype in JUNCTION_TYPES:
                    continue
                seen.add(nxt)
                if ntype == "inline_component":
                    inline.append(nxt)
                else:
                    components[nxt] = ntype
                if ntype in expandable and depth < 4 and kind != "stream":
                    frontier.append((nxt, depth + 1))
        # a final element named for this loop belongs to it even when not wired
        for key, entry in out_nodes.items():
            m = _ISA.match(entry["label"])
            if m and f"{m.group(1)}{m.group(3)}" == name and entry["type"] in ("valve", "regulator") \
                    and key not in components:
                components[key] = entry["type"]
        loop["instruments"].sort()
        loop["connected_components"] = [{"id": k, "type": t} for k, t in sorted(components.items())]
        loop["connected_inline"] = sorted(inline)

    # ── signal paths ─────────────────────────────────────────────────────────
    sig_out: dict[str, list] = defaultdict(list)
    sig_in: Counter = Counter()
    for e in edges:
        if e["kind"] in SIGNAL_KINDS:
            a, b = key_of[e["from"]], key_of[e["to"]]
            sig_out[a].append(b)
            sig_in[b] += 1

    def _ref(key: str) -> dict:
        entry = out_nodes[key]
        ref = {"id": key, "label": entry["label"], "type": entry["type"],
               "symbol_type": meta_of[key]["kind_detail"] or entry["type"], "point": entry["point"]}
        if entry.get("bbox"):
            ref["bbox"] = entry["bbox"]
        return ref

    signal_paths, chains = [], []
    starts = [k for k in sig_out if sig_in[k] == 0] or list(sig_out)[:1]
    for s in starts:
        stack = [(s, [s])]
        while stack and len(chains) < 500:
            cur, path = stack.pop()
            nxts = [n for n in sig_out.get(cur, []) if n not in path]
            if not nxts:
                if len(path) >= 2:
                    chains.append(path)
                continue
            for n in nxts:
                stack.append((n, path + [n]))
    for i, chain in enumerate(sorted(chains, key=lambda c: (c[0], len(c), c))):
        has_controller = any(_is_controller(out_nodes[k]["label"])
                             for k in chain if out_nodes[k]["type"] == "instrument")
        ends_at_element = out_nodes[chain[-1]]["type"] in ("valve", "mechanical", "regulator")
        signal_paths.append({
            "signal_id": f"SIG_{i + 1:03d}", "chain": list(chain), "chain_ids": list(chain),
            "start_node": _ref(chain[0]), "end_node": _ref(chain[-1]),
            "path": [_ref(k) for k in chain],
            "signal_role": "primary" if has_controller and ends_at_element else "secondary",
        })

    expansion_joints = [{"id": k, "point": v["point"]} for k, v in out_nodes.items()
                        if meta_of[k]["kind"] == "expansion_joint"]

    # ── electric heat tracing, keyed by the item each segment runs beside ────
    symbols = [(k, v) for k, v in out_nodes.items() if v["type"] not in JUNCTION_TYPES and v.get("bbox")]
    heat_trace: dict[str, list] = {}
    for ln in geo_lines.values():
        if ln.get("type") != "heat_trace" or len(ln.get("points") or []) < 2:
            continue
        page_key = (int(ln.get("source_id") or 0), int(ln.get("page") or 1))
        (x1, y1), (x2, y2) = ln["points"][0], ln["points"][-1]
        mid = ((x1 + x2) / 2, (y1 + y2) / 2, (x1 + x2) / 2, (y1 + y2) / 2)
        near = [(k, v) for k, v in symbols if meta_of[k]["page"] == page_key] or symbols
        if not near:
            continue
        _key, entry = min(near, key=lambda kv: _bbox_gap(mid, kv[1]["bbox"]))
        heat_trace.setdefault(entry["label"], []).append(
            {"points": [_round(x1), _round(y1), _round(x2), _round(y2)]})

    # ── loop groups: loops sharing a final element or linked by a signal ─────
    owner: dict[str, set] = defaultdict(set)
    for name, loop in loops.items():
        parts = {k for k, v in out_nodes.items() if v.get("control_loop", {}).get("loop_name") == name}
        parts |= {c["id"] for c in loop["connected_components"]}
        for k in parts:
            owner[k].add(name)
    links: dict[frozenset, set] = defaultdict(set)
    for owners in owner.values():
        for x in owners:
            for y in owners:
                if x < y:
                    links[frozenset((x, y))].add("shared_component")
    for e in edges:
        if e["kind"] not in SIGNAL_KINDS:
            continue
        for x in owner.get(key_of[e["from"]], ()):
            for y in owner.get(key_of[e["to"]], ()):
                if x != y:
                    links[frozenset((x, y))].add("signal")
    group_of = {n: n for n in loops}

    def _root(n: str) -> str:
        while group_of[n] != n:
            n = group_of[n]
        return n
    for pair in links:
        x, y = sorted(pair)
        rx, ry = _root(x), _root(y)
        if rx != ry:
            group_of[max(rx, ry)] = min(rx, ry)
    grouped: dict[str, list] = defaultdict(list)
    for n in sorted(loops):
        grouped[_root(n)].append(n)
    loop_groups = []
    for members in sorted(m for m in grouped.values() if len(m) > 1):
        member_set = set(members)
        kinds = sorted({kind for pair, ks in links.items() if pair <= member_set for kind in ks})
        shared = sorted(k for k, o in owner.items() if len(o & member_set) > 1)
        loop_groups.append({"group_id": f"LG_{len(loop_groups) + 1:03d}", "loops": members,
                            "links": kinds, "shared_components": shared})

    clusters = spatial_clusters([(k, v["bbox"], meta_of[k]["page"], meta_of[k]["dims"] or NOMINAL_PAGE)
                                 for k, v in symbols])

    geometry_state = ("available" if geo_lines and not pages.nominal_used
                      else "partial" if geo_lines else "unavailable")
    metadata = {
        "schema_version": schema_version, "diagram_type": "PID",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "node_count": len(out_nodes), "edge_count": len(out_edges), "line_count": len(out_lines),
        "node_types": dict(Counter(v["type"] for v in out_nodes.values())),
        "control_loops_count": len(loops), "loop_groups_count": len(loop_groups),
        "signal_paths_count": len(signal_paths), "spatial_clusters_count": len(clusters),
        "electric_heat_trace_count": len(heat_trace),
        "geometry": geometry_state,
    }
    if extended:
        metadata["project_id"] = pid
    return {"metadata": metadata, "nodes": out_nodes, "edges": out_edges, "lines": out_lines,
            "expansion_joints": expansion_joints, "control_loops": loops, "loop_groups": loop_groups,
            "signal_paths": signal_paths, "spatial_clusters": clusters,
            "electric_heat_trace": heat_trace}


def schema_path() -> Path:
    return Path(__file__).resolve().parent.parent / "schemas" / "connectivity_graph_2_0_0.schema.json"


def validate(document: dict) -> list[str]:
    """Schema violations as readable strings; empty when valid."""
    import jsonschema
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    return [f"{'/'.join(str(p) for p in err.path)}: {err.message}"
            for err in jsonschema.Draft7Validator(schema).iter_errors(document)]


def write_export(pid: str, exports_dir: Path, schema_version: str = SCHEMA_2_0) -> Path:
    document = build_connectivity_graph(pid, schema_version)
    exports_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if schema_version == SCHEMA_2_0 else "_" + schema_version.replace(".", "_")
    path = exports_dir / f"{pid}_connectivity{suffix}.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

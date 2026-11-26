"""
services/geometry_store.py — extraction geometry that outlives the extraction.

WHY THIS EXISTS
---------------
Extraction builds a precise geometric picture of every page: symbol bounding
boxes, detected pipe runs, three-way junctions, crossings with no junction dot,
dangling stubs. It used that picture to ground LLM connection audits, then threw
it away. Stored projects kept only node positions and edges, with no bbox, no
line polyline and no junction record, so nothing downstream could reconstruct a
connectivity graph at drawing fidelity.

This module persists that geometry per (project, document, page) in three
tables, all in the page's own raster pixel space:

  geometry_pages     (pid, source_id, page, width, height)
  geometry_lines     (pid, line_id, source_id, page, type, style, direction, points_json)
  geometry_junctions (pid, junction_id, source_id, page, kind, x, y, extra_json)

`source_id` 0 means "no document identity" (the Flask path, or a CLI run without
--source-id). Re-extracting a document replaces only that document's rows, so
other documents' geometry is never touched. `_db_persist_espx` wipes nodes and
edges wholesale but never these tables.
"""

from __future__ import annotations

import json
from typing import Any

#: Junction kinds, matching the connectivity-graph schema vocabulary.
T_JUNCTION = "t_junction"
ENDPOINT_SHARE = "endpoint_share"
CROSSOVER = "crossover"
OPEN_ENDPOINT = "open_endpoint"


def _db():
    from adapters.db import get_db
    return get_db()


#: Annotation line types. Stored beside pipe runs, never exported as `lines`.
FLOW_ARROW = "flow_arrow"
HEAT_TRACE = "heat_trace"


def page_geometry(geo_graph: dict | None, symbols: list[dict] | None,
                  width: float, height: float, annotations: dict | None = None) -> dict:
    """Package one page's geometric connectivity result for storage.

    `geo_graph` is connectivity_graph.build_geometric_connectivity output (or an
    equivalent candidate graph); `symbols` are detector symbols whose list
    position gives node id n{i+1}. Ids are UNSCOPED here; the caller scopes
    them with the same prefix it applies to node ids. `annotations` is
    llm_flow_annotation_service output: arrows become FLOW_ARROW lines
    [tail, tip] and heat tracing becomes HEAT_TRACE lines, numbered after the
    pipe runs so edge line_indices keep pointing at the same runs.
    """
    geo = geo_graph or {}
    lines = []
    for i, ln in enumerate(geo.get("lines") or []):
        try:
            pts = [[float(ln["x1"]), float(ln["y1"])], [float(ln["x2"]), float(ln["y2"])]]
        except (KeyError, TypeError, ValueError):
            continue
        kind = (ln.get("kind") or "process").lower()
        style = ln.get("style") or ("dashed" if kind == "signal" else "solid")
        lines.append({"index": i, "type": kind, "style": style,
                      "direction": ln.get("direction"), "points": pts})
    next_index = len(geo.get("lines") or [])
    for a in (annotations or {}).get("arrows") or []:
        lines.append({"index": next_index, "type": FLOW_ARROW, "style": "arrow",
                      "direction": None, "points": [list(a["tail"]), list(a["tip"])]})
        next_index += 1
    for seg in (annotations or {}).get("heat_trace") or []:
        lines.append({"index": next_index, "type": HEAT_TRACE, "style": HEAT_TRACE,
                      "direction": None, "points": [[seg[0], seg[1]], [seg[2], seg[3]]]})
        next_index += 1
    junctions = []
    for j in geo.get("junctions") or []:
        if j.get("x") is None or j.get("y") is None:
            continue
        degree = int(j.get("degree") or 3)
        junctions.append({"id": str(j.get("id")), "x": float(j["x"]), "y": float(j["y"]),
                          "kind": T_JUNCTION if degree >= 3 else ENDPOINT_SHARE,
                          "degree": degree})
    for i, c in enumerate(geo.get("ambiguous_crossings") or []):
        junctions.append({"id": f"cx_{i}", "x": float(c.get("x", 0)), "y": float(c.get("y", 0)),
                          "kind": CROSSOVER, "line_indices": c.get("line_indices") or []})
    for i, s in enumerate(geo.get("open_stubs") or []):
        junctions.append({"id": f"os_{i}", "x": float(s.get("x", 0)), "y": float(s.get("y", 0)),
                          "kind": OPEN_ENDPOINT, "line_index": s.get("line_index")})
    syms = [{"id": f"n{i + 1}", "bbox": s.get("bbox"), "type": s.get("type")}
            for i, s in enumerate(symbols or []) if s.get("bbox")]
    return {"width": float(width or 0), "height": float(height or 0),
            "lines": lines, "junctions": junctions, "symbols": syms}


def scope_page(geometry: dict, prefix: str) -> dict:
    """Apply a node-id prefix ("s3_p2_") to every geometry id on a page."""
    out = dict(geometry)
    out["lines"] = [{**ln, "id": f"{prefix}line_{ln['index']}"} for ln in geometry.get("lines") or []]
    out["junctions"] = [{**j, "id": f"{prefix}{j['id']}"} for j in geometry.get("junctions") or []]
    out["symbols"] = [{**s, "id": f"{prefix}{s['id']}"} for s in geometry.get("symbols") or []]
    return out


def link_edges_to_lines(edges: list[dict], prefix: str) -> None:
    """Replace per-page `line_indices` on edges with persistent `line_ids`."""
    for e in edges:
        idx = e.pop("line_indices", None)
        if idx:
            e["line_ids"] = [f"{prefix}line_{i}" for i in idx]


def stamp_symbol_bboxes(nodes: list[dict], geometry: dict) -> None:
    """Give each node that came from a detector symbol its pixel bbox."""
    by_id = {s["id"]: s["bbox"] for s in geometry.get("symbols") or []}
    for n in nodes:
        bbox = by_id.get(n.get("id"))
        if bbox and not n.get("bbox_px"):
            n["bbox_px"] = [round(float(v), 1) for v in bbox]


def persist_pages(pid: str, source_id: int | None, pages: list[dict]) -> dict:
    """Replace this document's geometry with `pages`.

    Each page: {page, width, height, lines:[{id,type,style,direction,points}],
    junctions:[{id,kind,x,y,...}]} with ids already scoped.
    """
    sid = int(source_id or 0)
    db = _db()
    db.execute("DELETE FROM geometry_pages WHERE pid=? AND source_id=?", (pid, sid))
    db.execute("DELETE FROM geometry_lines WHERE pid=? AND source_id=?", (pid, sid))
    db.execute("DELETE FROM geometry_junctions WHERE pid=? AND source_id=?", (pid, sid))
    n_lines = n_junctions = 0
    for p in pages or []:
        page = int(p.get("page") or 1)
        db.execute("INSERT OR REPLACE INTO geometry_pages (pid, source_id, page, width, height) "
                   "VALUES (?,?,?,?,?)", (pid, sid, page, p.get("width"), p.get("height")))
        for ln in p.get("lines") or []:
            db.execute(
                "INSERT OR REPLACE INTO geometry_lines (pid, line_id, source_id, page, type, "
                "style, direction, points_json) VALUES (?,?,?,?,?,?,?,?)",
                (pid, ln["id"], sid, page, ln.get("type"), ln.get("style"),
                 ln.get("direction"), json.dumps(ln.get("points") or [])))
            n_lines += 1
        for j in p.get("junctions") or []:
            extra = {k: v for k, v in j.items() if k not in ("id", "kind", "x", "y")}
            db.execute(
                "INSERT OR REPLACE INTO geometry_junctions (pid, junction_id, source_id, page, "
                "kind, x, y, extra_json) VALUES (?,?,?,?,?,?,?,?)",
                (pid, j["id"], sid, page, j.get("kind"), j.get("x"), j.get("y"),
                 json.dumps(extra)))
            n_junctions += 1
    db.commit()
    return {"pages": len(pages or []), "lines": n_lines, "junctions": n_junctions}


def load(pid: str) -> dict[str, Any]:
    """Everything stored for a project, keyed for the exporter."""
    db = _db()
    pages = {(int(r[0]), int(r[1])): {"width": r[2], "height": r[3]}
             for r in db.execute("SELECT source_id, page, width, height FROM geometry_pages "
                                 "WHERE pid=?", (pid,)).fetchall()}
    lines = [{"id": r[0], "source_id": r[1], "page": r[2], "type": r[3], "style": r[4],
              "direction": r[5], "points": json.loads(r[6] or "[]")}
             for r in db.execute("SELECT line_id, source_id, page, type, style, direction, "
                                 "points_json FROM geometry_lines WHERE pid=? ORDER BY rowid",
                                 (pid,)).fetchall()]
    junctions = [{"id": r[0], "source_id": r[1], "page": r[2], "kind": r[3], "x": r[4],
                  "y": r[5], **json.loads(r[6] or "{}")}
                 for r in db.execute("SELECT junction_id, source_id, page, kind, x, y, extra_json "
                                     "FROM geometry_junctions WHERE pid=? ORDER BY rowid",
                                     (pid,)).fetchall()]
    return {"pages": pages, "lines": lines, "junctions": junctions}


def summary(pid: str) -> dict:
    db = _db()
    return {k: db.execute(f"SELECT COUNT(*) FROM {t} WHERE pid=?", (pid,)).fetchone()[0]
            for k, t in (("pages", "geometry_pages"), ("lines", "geometry_lines"),
                         ("junctions", "geometry_junctions"))}

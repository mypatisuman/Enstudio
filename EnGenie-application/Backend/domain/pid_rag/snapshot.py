"""One canonical view of a built P&ID, whichever store holds it.

The describe workflow (greenfield authoring, brownfield digitisation and
retrofits, every chat edit) keeps the drawing in studio.db: nodes, edges, the
plant hierarchy, digitisation metadata, and the session's designed solution.
A solution-session drawing lives in Mongo as a PIDGraph. Both become the same
snapshot here, so cards and retrieval never care where a drawing came from.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

EQUIPMENT_KINDS = {"vessel", "tank", "column", "pump", "compressor", "heat_exchanger", "exchanger",
                   "reactor", "filter", "mixer", "equipment", "drum", "separator", "boiler",
                   "furnace", "blower", "fan", "package", "skid", "turbine", "dryer"}
TERMINAL_KINDS = {"tie_in", "off_page_connector", "header", "flag"}
SIGNAL_EDGE_KINDS = {"signal", "pneumatic", "electrical", "software", "data", "capillary"}


def role_of(kind: str) -> str:
    """equipment | terminal | junction | instrument (valves and instruments)."""
    k = (kind or "").strip().lower()
    if k in EQUIPMENT_KINDS:
        return "equipment"
    if k in TERMINAL_KINDS:
        return "terminal"
    if k == "junction":
        return "junction"
    return "instrument"


def _loads(text: Any) -> dict:
    if isinstance(text, dict):
        return text
    try:
        v = json.loads(text) if text else {}
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def _db():
    from adapters.db import get_db
    return get_db()


def _hierarchy(pid: str) -> dict[str, list[str]]:
    """node id -> its groups, outermost first (system, subsystem ...)."""
    db = _db()
    try:
        rows = db.execute("SELECT id, parent_id, level, name FROM hierarchy WHERE pid=?", (pid,)).fetchall()
        links = db.execute("SELECT node_id, hierarchy_id FROM node_hierarchy WHERE pid=?", (pid,)).fetchall()
    except Exception:
        return {}
    by_id = {r[0]: (r[1], r[2], r[3]) for r in rows}
    out: dict[str, list[str]] = {}
    for node_id, hid in links:
        chain, seen = [], set()
        while hid in by_id and hid not in seen:
            seen.add(hid)
            parent, level, name = by_id[hid]
            chain.append(f"{name} ({level})")
            hid = parent
        out[node_id] = list(reversed(chain))
    return out


def _designed_solution(pid: str) -> dict | None:
    """The most recently updated session's designed solution (greenfield
    rationale: objective, overview, component roles, assumptions)."""
    try:
        row = _db().execute(
            "SELECT active_solution_json FROM describe_session_states WHERE pid=? "
            "AND active_solution_json IS NOT NULL ORDER BY updated_at DESC LIMIT 1", (pid,)).fetchone()
    except Exception:
        return None
    sol = _loads(row[0]) if row else {}
    return sol or None


def _drawing_meta(pid: str) -> dict:
    try:
        row = _db().execute("SELECT meta_json, image_path FROM pid_drawing_meta WHERE pid=?", (pid,)).fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    meta = _loads(row[0])
    meta["image_path"] = row[1] or ""
    return meta


def load_snapshot(pid: str) -> dict:
    """The drawing held in studio.db for project `pid` (empty lists when none)."""
    db = _db()
    try:
        prow = db.execute("SELECT title, status FROM projects WHERE id=?", (pid,)).fetchone()
    except Exception:
        prow = None
    node_rows = db.execute(
        "SELECT id, label, kind, kind_detail, area, x, y, extra_json FROM nodes WHERE pid=?", (pid,)).fetchall()
    edge_rows = db.execute(
        "SELECT from_id, to_id, kind, label, extra_json FROM edges WHERE pid=?", (pid,)).fetchall()
    groups = _hierarchy(pid)
    nodes, tag_of = [], {}
    for r in node_rows:
        extra = _loads(r[7])
        tag = (r[1] or r[0] or "").strip()
        tag_of[r[0]] = tag
        nodes.append({"id": r[0], "tag": tag, "kind": (r[2] or "").strip().lower(), "kind_detail": r[3] or "",
                      "area": r[4] or "", "x": r[5], "y": r[6], "extra": extra, "groups": groups.get(r[0], [])})
    edges = []
    for f, t, k, label, extra in edge_rows:
        a, b = tag_of.get(f, f), tag_of.get(t, t)
        if a and b and a != b:
            edges.append({"from": a, "to": b, "kind": (k or "").strip().lower(), "label": label or "",
                          "extra": _loads(extra)})
    try:
        from agents.describe.services import repository as R
        loops = R.get_loops(pid)
    except Exception as exc:
        logger.debug("[pid_rag] loops unavailable for %s: %s", pid, exc)
        loops = []
    meta = _drawing_meta(pid)
    origins = {n["extra"].get("origin") or ("extracted" if n["extra"].get("source") == "brownfield_vision" else "authored")
               for n in nodes}
    source = ("brownfield" if origins == {"extracted"} else "greenfield" if origins <= {"authored"}
              else "brownfield (with authored changes)") if nodes else "none"
    return _finish({"pid": pid, "title": (prow[0] if prow else "") or pid, "status": (prow[1] if prow else "") or "",
                    "source": source, "nodes": nodes, "edges": edges, "loops": loops,
                    "design": _designed_solution(pid), "meta": meta})


def snapshot_from_pid_graph(graph: dict, pid: str = "") -> dict:
    """A solution-session PIDGraph (Mongo pid_graphs) as a snapshot."""
    nodes, tag_of = [], {}
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        tag = str(n.get("label") or n.get("tag") or n.get("id") or "").strip()
        tag_of[str(n.get("id") or tag)] = tag
        extra = {k: v for k, v in n.items() if k not in ("id", "label", "kind", "area", "x", "y") and v not in (None, "", [], {})}
        nodes.append({"id": str(n.get("id") or tag), "tag": tag, "kind": str(n.get("kind") or "").lower(),
                      "kind_detail": str(n.get("description") or ""), "area": str(n.get("area") or ""),
                      "x": n.get("x"), "y": n.get("y"), "extra": extra, "groups": []})
    edges = []
    for e in graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        a = tag_of.get(str(e.get("from") or e.get("from_id")), str(e.get("from") or e.get("from_id") or ""))
        b = tag_of.get(str(e.get("to") or e.get("to_id")), str(e.get("to") or e.get("to_id") or ""))
        if a and b and a != b:
            edges.append({"from": a, "to": b, "kind": str(e.get("kind") or "stream").lower(),
                          "label": str(e.get("label") or ""),
                          "extra": {k: e[k] for k in ("fluid", "line_size") if e.get(k)}})
    return _finish({"pid": pid or str(graph.get("session_id") or ""), "title": str(graph.get("title") or pid),
                    "status": str(graph.get("status") or ""), "source": str(graph.get("project_type") or "greenfield"),
                    "nodes": nodes, "edges": edges, "loops": [], "design": None,
                    "meta": {"summary": graph.get("summary") or "", "notes": graph.get("notes") or []}})


def _finish(snap: dict) -> dict:
    snap["tags"] = {n["tag"] for n in snap["nodes"] if n["tag"]}
    basis = json.dumps({"n": sorted((n["tag"], n["kind"], n["kind_detail"], n["area"], json.dumps(n["extra"], sort_keys=True, default=str), tuple(n["groups"])) for n in snap["nodes"]),
                        "e": sorted((e["from"], e["to"], e["kind"], e["label"]) for e in snap["edges"]),
                        "d": snap.get("design"), "m": snap.get("meta"), "t": snap.get("title")},
                       sort_keys=True, default=str)
    snap["content_hash"] = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    return snap

"""
services/hierarchy.py — the plant hierarchy a node belongs to.

Levels, top to bottom:  site > plant > unit > area > system > subsystem

The same six levels the MongoDB asset inventory already records under each
asset's `location`, so an inventory sync maps one to one. Before this module the
only grouping anywhere in the application was a free-text `area` string, so
"add a transmitter to the feed-supply subsystem" had nowhere to go.

Storage (identical DDL in adapters/db.py and src-tauri schema.rs):

  hierarchy(id, pid, parent_id, level, name, code, extra_json)
      parent_id = 0 marks a root. UNIQUE(pid, parent_id, level, name).
  node_hierarchy(pid, node_id, hierarchy_id)
      One entry per node: its deepest assigned level.

Ownership rule: hierarchy rows and assignments are keyed by node id, and
`_db_persist_espx` never deletes them, so they survive re-extraction. Authored
nodes keep their ids across re-extraction; extracted nodes may be renumbered, so
`bootstrap_from_areas` can rebuild their area assignment at any time.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

LEVELS = ("site", "plant", "unit", "area", "system", "subsystem")
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}


def _db():
    from adapters.db import get_db
    return get_db()


def _norm(s: str | None) -> str:
    return " ".join((s or "").split()).strip()


# ── Core rows ────────────────────────────────────────────────────────────────

def get_or_create(pid: str, level: str, name: str, parent_id: int = 0,
                  code: str | None = None, extra: dict | None = None) -> int:
    level = (level or "").strip().lower()
    if level not in _RANK:
        raise ValueError(f"unknown hierarchy level {level!r}; expected one of {LEVELS}")
    name = _norm(name)
    if not name:
        raise ValueError(f"a {level} needs a name")
    db = _db()
    row = db.execute(
        "SELECT id FROM hierarchy WHERE pid=? AND parent_id=? AND level=? "
        "AND lower(name)=lower(?)", (pid, int(parent_id), level, name)).fetchone()
    if row:
        return int(row[0])
    cur = db.execute(
        "INSERT INTO hierarchy (pid, parent_id, level, name, code, extra_json) "
        "VALUES (?,?,?,?,?,?)",
        (pid, int(parent_id), level, name, code, json.dumps(extra or {})))
    db.commit()
    return int(cur.lastrowid)


def ensure_path(pid: str, path: dict[str, str | None]) -> int | None:
    """Create any missing levels of `path` (level -> name) and return the id of
    the deepest named level. Skipped levels are allowed: a system can hang
    directly off an area, or off the project root."""
    parent = 0
    leaf = None
    for level in LEVELS:
        name = _norm((path or {}).get(level))
        if not name:
            continue
        parent = get_or_create(pid, level, name, parent_id=parent)
        leaf = parent
    return leaf


def get(pid: str, hierarchy_id: int) -> dict | None:
    r = _db().execute(
        "SELECT id, parent_id, level, name, code, extra_json FROM hierarchy "
        "WHERE pid=? AND id=?", (pid, int(hierarchy_id))).fetchone()
    if not r:
        return None
    return {"id": r[0], "parent_id": r[1], "level": r[2], "name": r[3],
            "code": r[4], "extra": json.loads(r[5] or "{}")}


def path_of(pid: str, hierarchy_id: int | None) -> dict[str, str]:
    """level -> name for `hierarchy_id` and every ancestor."""
    out: dict[str, str] = {}
    seen = set()
    hid = hierarchy_id
    while hid and hid not in seen:
        seen.add(hid)
        row = get(pid, hid)
        if not row:
            break
        out[row["level"]] = row["name"]
        hid = row["parent_id"]
    return out


def find(pid: str, name: str, level: str | None = None,
         parent_name: str | None = None) -> list[dict]:
    """Rows whose name matches: exact (case-insensitive) first, else contains.

    `parent_name` narrows to rows whose direct parent has that name, which is
    how "the feed subsystem of the reactor system" disambiguates.
    """
    name = _norm(name)
    if not name:
        return []
    sql = ("SELECT h.id, h.parent_id, h.level, h.name, p.name FROM hierarchy h "
           "LEFT JOIN hierarchy p ON p.id = h.parent_id AND p.pid = h.pid "
           "WHERE h.pid=?")
    args: list[Any] = [pid]
    if level:
        sql += " AND h.level=?"
        args.append(level.lower())
    rows = _db().execute(sql, args).fetchall()

    def _match(exact: bool) -> list[dict]:
        hits = []
        for r in rows:
            rn = (r[3] or "").lower()
            ok = rn == name.lower() if exact else name.lower() in rn
            if not ok:
                continue
            if parent_name and (r[4] or "").lower() != _norm(parent_name).lower() \
                    and _norm(parent_name).lower() not in (r[4] or "").lower():
                continue
            hits.append({"id": r[0], "parent_id": r[1], "level": r[2],
                         "name": r[3], "parent": r[4]})
        return hits

    return _match(True) or _match(False)


# ── Node assignment ──────────────────────────────────────────────────────────

def assign(pid: str, node_ids: Iterable[str], hierarchy_id: int) -> int:
    db = _db()
    n = 0
    for nid in node_ids:
        if not nid:
            continue
        db.execute(
            "INSERT INTO node_hierarchy (pid, node_id, hierarchy_id) VALUES (?,?,?) "
            "ON CONFLICT(pid, node_id) DO UPDATE SET hierarchy_id=excluded.hierarchy_id",
            (pid, nid, int(hierarchy_id)))
        n += 1
    db.commit()
    return n


def unassign(pid: str, node_ids: Iterable[str]) -> None:
    db = _db()
    for nid in node_ids:
        db.execute("DELETE FROM node_hierarchy WHERE pid=? AND node_id=?", (pid, nid))
    db.commit()


def node_assignment(pid: str, node_id: str) -> dict[str, str]:
    r = _db().execute(
        "SELECT hierarchy_id FROM node_hierarchy WHERE pid=? AND node_id=?",
        (pid, node_id)).fetchone()
    return path_of(pid, r[0]) if r else {}


def assignments(pid: str) -> dict[str, dict[str, str]]:
    """node_id -> {level: name} for every assigned node. One query per distinct
    hierarchy id, not per node."""
    rows = _db().execute(
        "SELECT node_id, hierarchy_id FROM node_hierarchy WHERE pid=?",
        (pid,)).fetchall()
    cache: dict[int, dict[str, str]] = {}
    out = {}
    for nid, hid in rows:
        if hid not in cache:
            cache[hid] = path_of(pid, hid)
        out[nid] = cache[hid]
    return out


def descendants(pid: str, hierarchy_id: int) -> set[int]:
    rows = _db().execute("SELECT id, parent_id FROM hierarchy WHERE pid=?",
                         (pid,)).fetchall()
    children: dict[int, list[int]] = {}
    for hid, parent in rows:
        children.setdefault(int(parent), []).append(int(hid))
    out, stack = {int(hierarchy_id)}, [int(hierarchy_id)]
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


def contents(pid: str, hierarchy_id: int, recursive: bool = True) -> list[str]:
    ids = descendants(pid, hierarchy_id) if recursive else {int(hierarchy_id)}
    marks = ",".join("?" * len(ids))
    rows = _db().execute(
        f"SELECT node_id FROM node_hierarchy WHERE pid=? AND hierarchy_id IN ({marks})",
        (pid, *ids)).fetchall()
    return [r[0] for r in rows]


def tree(pid: str) -> dict:
    """Nested hierarchy with direct and total node counts, for tools and UI."""
    db = _db()
    rows = db.execute("SELECT id, parent_id, level, name, code FROM hierarchy "
                      "WHERE pid=? ORDER BY id", (pid,)).fetchall()
    counts = dict(db.execute(
        "SELECT hierarchy_id, COUNT(*) FROM node_hierarchy WHERE pid=? "
        "GROUP BY hierarchy_id", (pid,)).fetchall())
    nodes = {r[0]: {"id": r[0], "level": r[2], "name": r[3], "code": r[4],
                    "direct_nodes": int(counts.get(r[0], 0)), "children": []}
             for r in rows}
    roots = []
    for r in rows:
        (nodes[r[1]]["children"] if r[1] in nodes else roots).append(nodes[r[0]])

    def _total(n):
        n["total_nodes"] = n["direct_nodes"] + sum(_total(c) for c in n["children"])
        return n["total_nodes"]

    for root in roots:
        _total(root)
    unassigned = db.execute(
        "SELECT COUNT(*) FROM nodes n WHERE n.pid=? AND NOT EXISTS (SELECT 1 FROM "
        "node_hierarchy h WHERE h.pid=n.pid AND h.node_id=n.id)", (pid,)).fetchone()[0]
    return {"roots": roots, "unassigned_nodes": int(unassigned)}


def delete(pid: str, hierarchy_id: int) -> int:
    """Remove a hierarchy entry and everything below it. Nodes are kept and
    become unassigned."""
    ids = descendants(pid, hierarchy_id)
    marks = ",".join("?" * len(ids))
    db = _db()
    db.execute(f"DELETE FROM node_hierarchy WHERE pid=? AND hierarchy_id IN ({marks})",
               (pid, *ids))
    db.execute(f"DELETE FROM hierarchy WHERE pid=? AND id IN ({marks})", (pid, *ids))
    db.commit()
    return len(ids)


# ── Seeding ──────────────────────────────────────────────────────────────────

def bootstrap_from_areas(pid: str) -> dict:
    """Create an `area` entry per distinct digitised node area, and assign every
    unassigned node that carries that area. Idempotent."""
    db = _db()
    rows = db.execute(
        "SELECT id, area FROM nodes n WHERE pid=? AND area IS NOT NULL AND area != '' "
        "AND NOT EXISTS (SELECT 1 FROM node_hierarchy h WHERE h.pid=n.pid AND h.node_id=n.id)",
        (pid,)).fetchall()
    by_area: dict[str, list[str]] = {}
    for nid, area in rows:
        by_area.setdefault(_norm(area), []).append(nid)
    created = 0
    assigned = 0
    for area, ids in by_area.items():
        before = db.execute("SELECT COUNT(*) FROM hierarchy WHERE pid=?", (pid,)).fetchone()[0]
        hid = get_or_create(pid, "area", area)
        after = db.execute("SELECT COUNT(*) FROM hierarchy WHERE pid=?", (pid,)).fetchone()[0]
        created += int(after > before)
        assigned += assign(pid, ids, hid)
    return {"areas": sorted(by_area), "created": created, "assigned": assigned}


def inventory_enabled() -> bool:
    """Asset-inventory access is opt-in: STUDIO_ASSET_INVENTORY=mongodb or the
    `asset_inventory` setting. Importing adapters.mongodb loads mongo.env with
    override=True, so it must never happen implicitly."""
    import os
    if (os.getenv("STUDIO_ASSET_INVENTORY") or "").strip().lower() == "mongodb":
        return True
    try:
        from adapters.config import load_config
        return (load_config().get("asset_inventory") or "").strip().lower() == "mongodb"
    except Exception:
        return False


def sync_from_inventory(pid: str, plant: str | None = None,
                        unit: str | None = None, fetch=None) -> dict:
    """Build the hierarchy from the asset inventory and assign nodes whose tag
    matches an asset's tag number.

    `fetch` is injectable for tests; by default it is
    adapters.mongodb.fetch_asset_inventory, used only when inventory access is
    enabled.
    """
    if fetch is None:
        if not inventory_enabled():
            return {"error": "asset inventory is not enabled (set "
                             "STUDIO_ASSET_INVENTORY=mongodb or the asset_inventory setting)"}
        from adapters.mongodb import fetch_asset_inventory as fetch
    assets = fetch(plant=plant, unit=unit, limit=5000) or []
    db = _db()
    labels = {(r[1] or "").upper(): r[0] for r in
              db.execute("SELECT id, label FROM nodes WHERE pid=?", (pid,)).fetchall()}
    leaves = 0
    assigned = 0
    for asset in assets:
        loc = asset.get("location") or {}
        hid = ensure_path(pid, {lvl: loc.get(lvl) for lvl in LEVELS})
        if not hid:
            continue
        leaves += 1
        tag = (asset.get("tag_number") or (asset.get("specifications") or {}).get("tag_number") or "").upper()
        if tag and tag in labels:
            assigned += assign(pid, [labels[tag]], hid)
    return {"assets": len(assets), "paths": leaves, "assigned_nodes": assigned,
            "tree": tree(pid)}

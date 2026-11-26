"""Shared data-access layer for the Describe specialists.

Pure DB operations over the same nodes/edges tables the extraction
workflow writes — one graph, two authors. This module contains NO agent
logic and NO tool registry: each dedicated specialist declares its own
tool subset over these functions. Guardrails are returned as
"ERROR: ..." strings the calling agent must react to.

delete_nodes is the EXECUTOR only — the human-confirmation interrupt
happens in the Deletion agent before this is called.
"""
from __future__ import annotations

import json
import re


def _db():
    from adapters.db import get_db
    return get_db()


# ── Read tools ───────────────────────────────────────────────────────────────

def search_graph(pid: str, query: str = "", kind_filter: str | None = None) -> list[dict]:
    sql = ("SELECT id, label, kind, kind_detail, area FROM nodes "
           "WHERE pid=? AND (label LIKE ? OR id LIKE ? OR kind LIKE ?)")
    args: list = [pid, f"%{query}%", f"%{query}%", f"%{query}%"]
    if kind_filter:
        sql += " AND kind=?"
        args.append(kind_filter)
    rows = _db().execute(sql + " LIMIT 40", args).fetchall()
    return [{"id": r[0], "tag": r[1] or r[0], "kind": r[2],
             "kind_detail": r[3], "area": r[4]} for r in rows]


def _find_node(pid: str, tag: str):
    return _db().execute(
        "SELECT id, label, kind, kind_detail, area, x, y, extra_json "
        "FROM nodes WHERE pid=? AND (label=? OR id=?)",
        (pid, tag, tag)).fetchone()


def get_node(pid: str, tag: str) -> dict:
    r = _find_node(pid, tag)
    if r is None:
        return {"error": f"ERROR: no node with tag '{tag}'"}
    return {"id": r[0], "tag": r[1] or r[0], "kind": r[2], "kind_detail": r[3],
            "area": r[4], "x": r[5], "y": r[6], "extra_json": r[7],
            "connections": get_connections(pid, tag)}


def get_connections(pid: str, tag: str) -> list[dict]:
    r = _find_node(pid, tag)
    if r is None:
        return []
    nid = r[0]
    rows = _db().execute(
        "SELECT from_id, to_id, kind FROM edges "
        "WHERE pid=? AND (from_id=? OR to_id=?)", (pid, nid, nid)).fetchall()
    out = []
    for f, t, k in rows:
        other = t if f == nid else f
        o = _db().execute("SELECT label FROM nodes WHERE pid=? AND id=?",
                          (pid, other)).fetchone()
        out.append({"direction": "out" if f == nid else "in",
                    "other": (o[0] if o and o[0] else other), "kind": k})
    return out


def validate_drawing(pid: str) -> dict:
    db = _db()
    n_nodes = db.execute("SELECT COUNT(*) FROM nodes WHERE pid=?",
                         (pid,)).fetchone()[0]
    orphans = db.execute(
        "SELECT COUNT(*) FROM nodes n WHERE n.pid=? AND NOT EXISTS "
        "(SELECT 1 FROM edges e WHERE e.pid=n.pid AND "
        "(e.from_id=n.id OR e.to_id=n.id))", (pid,)).fetchone()[0]
    dupes = db.execute(
        "SELECT COUNT(*) FROM (SELECT label FROM nodes WHERE pid=? AND "
        "label IS NOT NULL AND label != '' GROUP BY label "
        "HAVING COUNT(*) > 1)", (pid,)).fetchone()[0]
    missing_kind = db.execute(
        "SELECT COUNT(*) FROM nodes WHERE pid=? AND "
        "(kind IS NULL OR kind='')", (pid,)).fetchone()[0]
    score = 100
    if n_nodes:
        score -= min(50, round(50 * orphans / n_nodes))
        score -= min(30, 15 * dupes)
        score -= min(20, round(20 * missing_kind / n_nodes))
    return {"nodes": n_nodes, "orphans": orphans, "duplicate_tags": dupes,
            "missing_kinds": missing_kind, "score": max(0, score)}


def graph_summary(pid: str, max_tags: int = 40) -> str:
    db = _db()
    n_nodes = db.execute("SELECT COUNT(*) FROM nodes WHERE pid=?",
                         (pid,)).fetchone()[0]
    n_edges = db.execute("SELECT COUNT(*) FROM edges WHERE pid=?",
                         (pid,)).fetchone()[0]
    rows = db.execute(
        "SELECT label, kind FROM nodes WHERE pid=? AND label IS NOT NULL "
        "AND label != '' LIMIT ?", (pid, max_tags)).fetchall()
    tags = ", ".join(f"{r[0]}({r[1]})" for r in rows)
    summary = f"{n_nodes} nodes, {n_edges} edges. Tags: {tags or '(none yet)'}"
    try:
        groups = _hierarchy_names(pid)
    except Exception:
        groups = []
    if groups:
        names = ", ".join(f"{g['name']} [{g['level']}]" for g in groups)
        summary += f". Plant groups: {names}"
    return summary


# ── Write tools ──────────────────────────────────────────────────────────────

# ── Authored rows, placement and inheritance ─────────────────────────────────
#
# Every row a Describe agent writes is marked origin="authored". Extraction's
# re-merge rule (extraction_cli.commands._rows_from_other_sources) carries
# authored rows through EVERY re-extraction. Before this, agent rows had
# source_id NULL, and a re-extraction without --source-id silently deleted them.

AUTHORED = "authored"

#: Keys copied from the anchor node so a new node lands in the same drawing
#: cell on the canvas, and so the connectivity export can convert its
#: normalised position back to pixels on the right page.
_INHERITED_KEYS = ("drawing", "page", "page_w", "page_h")


def _authored_json(extra: dict | None = None) -> str:
    out = dict(extra or {})
    out.setdefault("source", "describe_agent")
    out["origin"] = AUTHORED
    return json.dumps(out)


def _extra_of(row) -> dict:
    try:
        value = json.loads(row[7] or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _inherit(pid: str, ref: str | None) -> dict:
    r = _find_node(pid, ref) if ref else None
    if r is None:
        return {}
    extra = _extra_of(r)
    out = {k: extra[k] for k in _INHERITED_KEYS if extra.get(k) not in (None, "")}
    # Authored rows keep source_id NULL (that is what lets re-extraction carry
    # them), so remember the anchor's document separately: the connectivity
    # export needs it to find the page raster this node is drawn on.
    row = _db().execute("SELECT source_id FROM nodes WHERE pid=? AND id=?",
                        (pid, r[0])).fetchone()
    anchor_sid = row[0] if row and row[0] is not None else extra.get("anchor_source_id")
    if anchor_sid is not None:
        out["anchor_source_id"] = anchor_sid
    return out


def _positions(pid: str) -> dict[str, tuple[float, float]]:
    """tag/id -> (x, y) for every positioned node in the project."""
    out: dict[str, tuple[float, float]] = {}
    for nid, label, x, y in _db().execute(
            "SELECT id, label, x, y FROM nodes WHERE pid=? AND x IS NOT NULL "
            "AND y IS NOT NULL", (pid,)).fetchall():
        p = (float(x), float(y))
        out.setdefault(nid, p)
        if label:
            out[label] = p
    return out


def _spot_near(pid: str, anchor: str | None, direction: str | None = None,
               exclude: str | None = None) -> tuple[float, float]:
    """A free position beside `anchor`, in the project's own coordinate space."""
    from services.placement import (SheetSpace, parse_direction,
                                    pick_free_spot, seed_spot)
    pos = _positions(pid)
    occupied = [p for k, p in pos.items() if k != exclude]
    space = SheetSpace.detect(pos.values())
    preferred = parse_direction(direction) if direction else None
    if anchor and anchor in pos:
        return pick_free_spot(pos[anchor], occupied, preferred, space)
    r = _find_node(pid, anchor) if anchor else None
    if r is not None and r[5] is not None:
        return pick_free_spot((float(r[5]), float(r[6] or 0)), occupied, preferred, space)
    return seed_spot(len(occupied), occupied, space)


def _resolve_group(pid: str, subsystem: str | None,
                   system: str | None) -> tuple[int | None, str | None]:
    """(hierarchy_id, None) or (None, error text naming the candidates)."""
    from services import hierarchy as H
    if not subsystem and not system:
        return None, None
    if subsystem:
        hits = H.find(pid, subsystem, level="subsystem", parent_name=system)
        if not hits:
            hits = [h for h in H.find(pid, subsystem) if h["level"] in ("subsystem", "system")]
        wanted, label = subsystem, "subsystem"
    else:
        hits = H.find(pid, system, level="system")
        wanted, label = system, "system"
    if len(hits) == 1:
        return hits[0]["id"], None
    if not hits:
        known = [f"{h['name']} ({h['level']})" for h in _hierarchy_names(pid)]
        return None, (f"ERROR: no {label} named '{wanted}'. Known: {known or 'none yet'}. "
                      "Create it with create_subsystem, or ask the engineer which "
                      "one they mean.")
    options = [f"{h['name']} in {h.get('parent') or 'project root'}" for h in hits]
    return None, (f"ERROR: '{wanted}' is ambiguous: {options}. Ask the engineer "
                  "which one, or pass system=... to narrow it.")


def _hierarchy_names(pid: str, levels=("system", "subsystem"), limit: int = 40) -> list[dict]:
    marks = ",".join("?" * len(levels))
    rows = _db().execute(
        f"SELECT h.name, h.level, p.name FROM hierarchy h LEFT JOIN hierarchy p "
        f"ON p.id=h.parent_id AND p.pid=h.pid WHERE h.pid=? AND h.level IN ({marks}) "
        f"ORDER BY h.level, h.name LIMIT ?", (pid, *levels, limit)).fetchall()
    return [{"name": r[0], "level": r[1], "parent": r[2]} for r in rows]


def _assign_to(pid: str, node_ids: list[str], hierarchy_id: int | None,
               fallback_from: str | None = None) -> str:
    """Assign nodes to `hierarchy_id`, or to the anchor's own group when none
    was named. Returns a short note for the tool result."""
    from services import hierarchy as H
    hid = hierarchy_id
    if hid is None and fallback_from:
        r = _find_node(pid, fallback_from)
        if r is not None:
            row = _db().execute("SELECT hierarchy_id FROM node_hierarchy WHERE "
                                "pid=? AND node_id=?", (pid, r[0])).fetchone()
            hid = row[0] if row else None
    if hid is None:
        return ""
    H.assign(pid, node_ids, hid)
    path = H.path_of(pid, hid)
    leaf = path.get("subsystem") or path.get("system") or next(iter(path.values()), "")
    return f"; assigned to {leaf}"


def _spec_fields(tag: str, node: dict) -> dict:
    from services.asset_specs import resolve
    return resolve(tag, node.get("specifications"), node.get("instrument_config"))


# ── Instrument/equipment/connection mirroring (Gap fix) ─────────────────────
# The CREATE path (add_nodes/add_edges/insert_between) historically wrote
# only to nodes/edges — export_vids/export_ympl/export_markdown and the
# Sidebar/Review screens all read instruments/equipment/connections instead,
# so a Describe-authored node or edge was invisible everywhere except the
# live Canvas. RENAME (_cascade_rename_tag_refs) and DELETE
# (_cascade_delete_tag_refs) already assume instruments/equipment/
# connections are correctly populated and cascade into them — they just had
# nothing to cascade from. This mirrors the same split the desktop app's
# Rust write path already uses for node creation (is_instrument_kind /
# mirror_node_to_instrument_or_equipment in src-tauri/src/commands/graph.rs)
# and extends it to also cover edges -> connections, which neither the
# Python nor the Rust create path previously did.

_INSTRUMENT_KINDS = {
    "transmitter", "controller", "indicator", "recorder", "switch",
    "alarm", "analyzer", "element", "meter", "gauge", "sensor",
}


def _is_instrument_kind(kind: str) -> bool:
    return (kind or "").strip().lower() in _INSTRUMENT_KINDS


def _mirror_node_to_instrument_or_equipment(pid: str, tag: str, kind: str,
                                            area: str) -> None:
    db = _db()
    kind = kind or ""
    if _is_instrument_kind(kind):
        db.execute(
            "INSERT OR IGNORE INTO instruments "
            "(tag, pid, area, kind_detail, type, equipment_ref, extra_json) "
            "VALUES (?,?,?,?,?,'','{}')",
            (tag, pid, area or "", kind, kind))
    else:
        db.execute(
            "INSERT OR IGNORE INTO equipment "
            "(tag, pid, area, kind_detail, type, extra_json) "
            "VALUES (?,?,?,?,?,'{}')",
            (tag, pid, area or "", kind, kind))


def _mirror_edge_to_connection(pid: str, edge_id: int, from_tag: str,
                               to_tag: str, kind: str) -> None:
    db = _db()
    db.execute(
        "INSERT OR REPLACE INTO connections "
        "(id, pid, from_tag, to_tag, type, extra_json) VALUES (?,?,?,?,?,?)",
        (f"e{edge_id}", pid, from_tag, to_tag, kind,
         json.dumps({"source": "describe_agent"})))


def _unmirror_connection_between(pid: str, from_tag: str, to_tag: str) -> None:
    db = _db()
    db.execute(
        "DELETE FROM connections WHERE pid=? AND "
        "((from_tag=? AND to_tag=?) OR (from_tag=? AND to_tag=?))",
        (pid, from_tag, to_tag, to_tag, from_tag))


def add_nodes(pid: str, nodes: list[dict], near_tag: str | None = None,
              subsystem: str | None = None, system: str | None = None,
              direction: str | None = None) -> str:
    """Add equipment or instruments beside an existing node.

    nodes: [{tag, kind, area?, description?, near_tag?, specifications?}].
    Each node is placed next to its own near_tag, else the previous node in the
    list, else the call's near_tag, inside the drawing. `specifications` only
    when the engineer stated them; nothing is invented. `subsystem`/`system`
    assign the new nodes to that plant group.
    """
    if not nodes or not isinstance(nodes, list) or \
            any(not isinstance(n, dict) for n in nodes):
        return "ERROR: nodes must be a non-empty list of objects"
    tags = [str(n.get("tag") or "").strip() for n in nodes]
    if any(not t for t in tags):
        return "ERROR: every node needs a tag"
    if len(set(tags)) != len(tags):
        return f"ERROR: the same tag appears twice in this request: {tags}"
    dupes = [t for t in tags if _find_node(pid, t) is not None]
    if dupes:
        return (f"ERROR: tags already exist: {dupes}. Use update_node, or "
                "next_tag to get free tags.")
    if near_tag and _find_node(pid, near_tag) is None:
        return f"ERROR: near_tag '{near_tag}' does not exist"
    for n in nodes:
        if n.get("near_tag") and _find_node(pid, n["near_tag"]) is None \
                and n["near_tag"] not in tags:
            return f"ERROR: near_tag '{n['near_tag']}' does not exist"
    group, err = _resolve_group(pid, subsystem, system)
    if err:
        return err

    from services.placement import parse_direction, place_new_nodes
    chain = []
    for i, (n, tag) in enumerate(zip(nodes, tags)):
        anchor = n.get("near_tag") or (tags[i - 1] if i else near_tag)
        if anchor:
            chain.append((anchor, tag))
    placed = place_new_nodes(_positions(pid), tags, chain,
                             parse_direction(direction) if direction else None,
                             anchor_tag=near_tag)

    db = _db()
    anchor_row = _find_node(pid, near_tag) if near_tag else None
    statuses = {}
    for n, tag in zip(nodes, tags):
        own_anchor = n.get("near_tag") or near_tag
        area = n.get("area") or (anchor_row[4] if anchor_row is not None else "") or ""
        extra = {"description": n.get("description", ""),
                 **_inherit(pid, own_anchor if _find_node(pid, own_anchor or "") else near_tag),
                 **_spec_fields(tag, n)}
        statuses[extra["spec_status"]] = statuses.get(extra["spec_status"], 0) + 1
        x, y = placed[tag]
        db.execute(
            "INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y,"
            " extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (tag, pid, n.get("kind", ""), n.get("kind_detail", ""), tag,
             area, x, y, _authored_json(extra)))
        _mirror_node_to_instrument_or_equipment(pid, tag, n.get("kind", ""), area)
    db.commit()
    note = _assign_to(pid, tags, group, fallback_from=near_tag)
    specs = ", ".join(f"{k}={v}" for k, v in sorted(statuses.items()))
    return f"Added {len(tags)} node(s): {tags}{note}. Specifications: {specs}."


def _infer_edge_kind(f_tag: str, t_tag: str, kind: str | None) -> str:
    kind = (kind or "stream").lower()
    if kind != "stream":
        return kind
    if "PSV" in f_tag or "PRV" in f_tag or "VENT" in t_tag or "FLARE" in t_tag:
        return "relief"
    if any(f_tag.startswith(p) for p in ("PI-", "TI-", "PT-", "TT-", "FT-", "LT-", "AI-", "PE-", "TE-", "FE-", "LE-")):
        if any(t_tag.startswith(c) for c in ("PIC-", "TIC-", "FIC-", "LIC-", "AIC-", "DCS-", "PLC-", "SIS-")):
            return "signal"
        return "impulse"
    if any(t_tag.startswith(p) for p in ("PI-", "TI-", "PT-", "TT-", "FT-", "LT-", "AI-")):
        return "impulse"
    if any(f_tag.startswith(c) for c in ("PIC-", "TIC-", "FIC-", "LIC-", "AIC-")):
        if any(t_tag.startswith(v) for v in ("PCV-", "TCV-", "FCV-", "LCV-", "CV-", "FV-", "PV-", "TV-", "LV-")):
            return "pneumatic"
        return "signal"
    return kind


def _edge_exists(pid: str, f_id: str, t_id: str, kind: str) -> bool:
    return _db().execute(
        "SELECT 1 FROM edges WHERE pid=? AND kind=? AND ((from_id=? AND to_id=?) "
        "OR (from_id=? AND to_id=?)) LIMIT 1",
        (pid, kind, f_id, t_id, t_id, f_id)).fetchone() is not None


def _insert_edge(pid: str, f_row, t_row, kind: str) -> bool:
    """Insert one authored edge unless an identical one exists. True if added."""
    f_id, t_id = f_row[0], t_row[0]
    if _edge_exists(pid, f_id, t_id, kind):
        return False
    cur = _db().execute(
        "INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json)"
        " VALUES (?,?,?,?,?,?)",
        (pid, f_id, t_id, kind, "", _authored_json()))
    _mirror_edge_to_connection(pid, cur.lastrowid, f_row[1] or f_id,
                               t_row[1] or t_id, kind)
    return True


def add_edges(pid: str, edges: list[dict]) -> str:
    """Connect existing nodes. edges: [{from_tag, to_tag, kind}].

    kind: stream | impulse | signal | pneumatic | relief | bypass. A connection
    that already exists between the same two nodes with the same kind is
    skipped, never duplicated.
    """
    if not edges or not isinstance(edges, list):
        return "ERROR: edges must be a non-empty list"
    resolved = []
    for e in edges:
        f_tag, t_tag = e.get("from_tag", ""), e.get("to_tag", "")
        f, t = _find_node(pid, f_tag), _find_node(pid, t_tag)
        if f is None or t is None:
            missing = f_tag if f is None else t_tag
            return (f"ERROR: tag '{missing}' does not exist. Add it first "
                    "with add_nodes.")
        resolved.append((f, t, _infer_edge_kind(f_tag, t_tag, e.get("kind")), f_tag, t_tag))
    added, skipped, seen = 0, [], set()
    for f, t, kind, f_tag, t_tag in resolved:
        key = (frozenset((f[0], t[0])), kind)
        if key in seen or not _insert_edge(pid, f, t, kind):
            skipped.append(f"{f_tag}-{t_tag}({kind})")
            continue
        seen.add(key)
        added += 1
    _db().commit()
    if not added:
        return f"NOOP: all {len(skipped)} connection(s) already exist: {skipped}"
    note = f" Skipped {len(skipped)} existing: {skipped}." if skipped else ""
    return f"Added {added} edge(s).{note}"


def add_junction(pid: str, near_tag: str | None = None) -> str:
    """Add a three-way piping tee beside near_tag. Returns its id, which
    add_edges accepts like any tag."""
    if near_tag and _find_node(pid, near_tag) is None:
        return f"ERROR: near_tag '{near_tag}' does not exist"
    n = _db().execute("SELECT COUNT(*) FROM nodes WHERE pid=? AND kind='junction'",
                      (pid,)).fetchone()[0]
    jid = f"j{n + 1}"
    while _find_node(pid, jid) is not None:
        n += 1
        jid = f"j{n + 1}"
    x, y = _spot_near(pid, near_tag)
    db = _db()
    db.execute(
        "INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y, "
        "extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (jid, pid, "junction", "", jid, "", x, y,
         _authored_json(_inherit(pid, near_tag))))
    db.commit()
    return f"Added junction {jid}."


def _cascade_rename_tag_refs(pid: str, old_tag: str, new_tag: str) -> None:
    """Keep every tag-KEYED table in sync after a rename. `nodes` is
    id-keyed so the rename above already covers it; `instruments`,
    `equipment`, `review`, and `connections` are all keyed (fully or
    partly) by the tag STRING, not the node id, so a rename must be
    mirrored into them or they silently point at a tag that no longer
    exists. Ported from the Rust desktop app's update_node_by_tag
    (src-tauri/src/commands/graph.rs) — this is the one graph-mutation
    code path this rebuild treats as canonical; Rust's equivalent is
    legacy being retired, not a peer to stay in sync with."""
    db = _db()
    db.execute("UPDATE instruments SET tag=? WHERE pid=? AND tag=?",
              (new_tag, pid, old_tag))
    db.execute("UPDATE equipment SET tag=? WHERE pid=? AND tag=?",
              (new_tag, pid, old_tag))
    db.execute("UPDATE review SET key=? WHERE pid=? AND key=?",
              (new_tag, pid, old_tag))
    db.execute("UPDATE instruments SET equipment_ref=? WHERE pid=? AND "
              "equipment_ref=?", (new_tag, pid, old_tag))
    db.execute("UPDATE connections SET from_tag=? WHERE pid=? AND from_tag=?",
              (new_tag, pid, old_tag))
    db.execute("UPDATE connections SET to_tag=? WHERE pid=? AND to_tag=?",
              (new_tag, pid, old_tag))


def _cascade_delete_tag_refs(pid: str, tag: str) -> None:
    """Same cascade family as _cascade_rename_tag_refs, for the delete
    case: remove the tag's rows from every tag-keyed table and clear any
    dangling equipment_ref that pointed at it. Ported from Rust's
    cascade_delete_tag_refs (src-tauri/src/commands/graph.rs)."""
    db = _db()
    db.execute("DELETE FROM instruments WHERE pid=? AND tag=?", (pid, tag))
    db.execute("DELETE FROM equipment WHERE pid=? AND tag=?", (pid, tag))
    db.execute("DELETE FROM review WHERE pid=? AND key=?", (pid, tag))
    db.execute("DELETE FROM connections WHERE pid=? AND "
              "(from_tag=? OR to_tag=?)", (pid, tag, tag))
    db.execute("UPDATE instruments SET equipment_ref='' WHERE pid=? AND "
              "equipment_ref=?", (pid, tag))


def update_node(pid: str, tag: str, new_tag: str | None = None,
                kind: str | None = None, area: str | None = None,
                description: str | None = None,
                move_near: str | None = None, direction: str | None = None,
                subsystem: str | None = None, system: str | None = None) -> str:
    """Rename, reclassify, describe, move beside another node, or move into a
    subsystem. Only pass the fields that change."""
    r = _find_node(pid, tag)
    if r is None:
        return f"ERROR: no node with tag '{tag}'"
    if new_tag and new_tag != tag and _find_node(pid, new_tag) is not None:
        return f"ERROR: tag '{new_tag}' already exists"
    if move_near and _find_node(pid, move_near) is None:
        return f"ERROR: move_near '{move_near}' does not exist"
    group, err = _resolve_group(pid, subsystem, system)
    if err:
        return err
    db = _db()
    nid = r[0]
    old_label = r[1]
    if new_tag:
        db.execute("UPDATE nodes SET label=? WHERE pid=? AND id=?",
                   (new_tag, pid, nid))
        # Cascade on the actual former LABEL, not the `tag` argument --
        # callers may pass a node id (Holistic-resolved target) as `tag`,
        # and instruments/equipment/review/connections are keyed by the
        # label string, never the node id.
        if old_label and old_label != new_tag:
            _cascade_rename_tag_refs(pid, old_label, new_tag)
    if kind:
        db.execute("UPDATE nodes SET kind=? WHERE pid=? AND id=?",
                   (kind, pid, nid))
    if area is not None:
        db.execute("UPDATE nodes SET area=? WHERE pid=? AND id=?",
                   (area, pid, nid))
    if description is not None:
        extra = _extra_of(r)
        extra["description"] = description
        db.execute("UPDATE nodes SET extra_json=? WHERE pid=? AND id=?",
                   (json.dumps(extra), pid, nid))
    if move_near:
        x, y = _spot_near(pid, move_near, direction, exclude=old_label or nid)
        db.execute("UPDATE nodes SET x=?, y=? WHERE pid=? AND id=?",
                   (x, y, pid, nid))
    db.commit()
    note = _assign_to(pid, [nid], group) if group is not None else ""
    return f"Updated {tag}{note}."


def insert_between(pid: str, new_node: dict, node_a: str, node_b: str,
                   at_fraction: float = 0.5, subsystem: str | None = None,
                   system: str | None = None) -> str:
    """Atomically insert an inline element between two nodes: add new_node,
    connect A->new->B, and remove any direct A-B edge. The new connections
    keep the kind of the line they replace (stream when there was none).

    node_a/node_b accept unique node ids (preferred, e.g. from the Holistic
    gate's resolved target, so duplicated tags cannot re-ambiguate here) or
    plain tags. at_fraction places the element along the line from A (0) to B (1).
    """
    ra, rb = _find_node(pid, node_a), _find_node(pid, node_b)
    if ra is None:
        return f"ERROR: '{node_a}' does not exist"
    if rb is None:
        return f"ERROR: '{node_b}' does not exist"
    if not isinstance(new_node, dict):
        return "ERROR: new_node must be an object with at least a tag"
    tag = new_node.get("tag")
    if not tag:
        return "ERROR: the new node needs a tag"
    if _find_node(pid, tag) is not None:
        return (f"ERROR: tags already exist: ['{tag}']. Use update_node or "
                "pick new tags.")
    group, err = _resolve_group(pid, subsystem, system)
    if err:
        return err

    db = _db()
    ida, idb = ra[0], rb[0]
    tag_a, tag_b = ra[1] or ida, rb[1] or idb
    old = db.execute(
        "SELECT kind FROM edges WHERE pid=? AND ((from_id=? AND to_id=?) OR "
        "(from_id=? AND to_id=?))", (pid, ida, idb, idb, ida)).fetchall()
    line_kind = (old[0][0] if old and old[0][0] else "stream")
    frac = min(1.0, max(0.0, float(at_fraction if at_fraction is not None else 0.5)))
    area = new_node.get("area", ra[4] or "")
    ax, ay = float(ra[5] or 0), float(ra[6] or 0)
    bx, by = float(rb[5] or 0), float(rb[6] or 0)
    x, y = ax + (bx - ax) * frac, ay + (by - ay) * frac
    extra = {"description": new_node.get("description", ""),
             **_inherit(pid, node_a), **_spec_fields(tag, new_node)}
    db.execute(
        "INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y,"
        " extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (tag, pid, new_node.get("kind", ""), new_node.get("kind_detail", ""),
         tag, area, x, y, _authored_json(extra)))
    _mirror_node_to_instrument_or_equipment(
        pid, tag, new_node.get("kind", ""), area)
    cur = db.execute(
        "DELETE FROM edges WHERE pid=? AND ((from_id=? AND to_id=?) OR "
        "(from_id=? AND to_id=?))", (pid, ida, idb, idb, ida))
    removed = cur.rowcount
    if removed:
        _unmirror_connection_between(pid, tag_a, tag_b)
    new_row = _find_node(pid, tag)
    _insert_edge(pid, ra, new_row, line_kind)
    _insert_edge(pid, new_row, rb, line_kind)
    db.commit()
    note = _assign_to(pid, [tag], group, fallback_from=node_a)
    removed_note = "; removed the old direct edge" if removed else ""
    return f"Inserted {tag} between {tag_a} and {tag_b}{removed_note}{note}."


def break_line(pid: str, from_tag: str, to_tag: str, new_node: dict,
               at_fraction: float = 0.5, subsystem: str | None = None,
               system: str | None = None) -> str:
    """Tie into an EXISTING line: split the connection between from_tag and
    to_tag and put new_node inline, keeping the line's kind. Fails when the two
    nodes are not directly connected (use insert_between to create a new run)."""
    ra, rb = _find_node(pid, from_tag), _find_node(pid, to_tag)
    if ra is None or rb is None:
        return f"ERROR: '{from_tag if ra is None else to_tag}' does not exist"
    exists = _db().execute(
        "SELECT 1 FROM edges WHERE pid=? AND ((from_id=? AND to_id=?) OR "
        "(from_id=? AND to_id=?)) LIMIT 1",
        (pid, ra[0], rb[0], rb[0], ra[0])).fetchone()
    if not exists:
        return (f"ERROR: there is no line between {from_tag} and {to_tag} to "
                "break. Check get_connections, or use insert_between to create one.")
    return insert_between(pid, new_node, from_tag, to_tag, at_fraction,
                          subsystem, system)


def reroute_edge(pid: str, from_tag: str, old_to: str, new_to: str,
                 kind: str | None = None) -> str:
    """Move one end of an existing connection: from_tag-old_to becomes
    from_tag-new_to, keeping its direction and kind unless kind is given."""
    rf, ro, rn = _find_node(pid, from_tag), _find_node(pid, old_to), _find_node(pid, new_to)
    for ref, row in ((from_tag, rf), (old_to, ro), (new_to, rn)):
        if row is None:
            return f"ERROR: '{ref}' does not exist"
    db = _db()
    row = db.execute(
        "SELECT id, from_id, to_id, kind FROM edges WHERE pid=? AND ((from_id=? AND to_id=?) "
        "OR (from_id=? AND to_id=?)) LIMIT 1",
        (pid, rf[0], ro[0], ro[0], rf[0])).fetchone()
    if row is None:
        return f"ERROR: no connection between {from_tag} and {old_to}"
    edge_id, e_from, e_to, e_kind = row
    new_kind = kind or e_kind or "stream"
    forward = e_from == rf[0]
    src_row, dst_row = (rf, rn) if forward else (rn, rf)
    if _edge_exists(pid, src_row[0], dst_row[0], new_kind):
        db.execute("DELETE FROM edges WHERE pid=? AND id=?", (pid, edge_id))
        _unmirror_connection_between(pid, rf[1] or rf[0], ro[1] or ro[0])
        db.commit()
        return (f"Removed {from_tag}-{old_to}: {from_tag}-{new_to} ({new_kind}) "
                "already existed.")
    if forward:
        db.execute("UPDATE edges SET to_id=?, kind=? WHERE pid=? AND id=?",
                   (rn[0], new_kind, pid, edge_id))
    else:
        db.execute("UPDATE edges SET from_id=?, kind=? WHERE pid=? AND id=?",
                   (rn[0], new_kind, pid, edge_id))
    _unmirror_connection_between(pid, rf[1] or rf[0], ro[1] or ro[0])
    _mirror_edge_to_connection(pid, edge_id, src_row[1] or src_row[0],
                               dst_row[1] or dst_row[0], new_kind)
    db.commit()
    return f"Rerouted {from_tag}-{old_to} to {from_tag}-{new_to} ({new_kind})."


def delete_nodes(pid: str, tags: list[str], reason: str = "") -> str:
    """Executor only — call AFTER the interrupt confirmation. Cascades
    the delete into instruments/equipment/review/connections so no
    stale tag-keyed row survives the node it referenced (see
    _cascade_delete_tag_refs)."""
    db = _db()
    deleted = 0
    for tag in tags:
        r = _find_node(pid, tag)
        if r is None:
            continue
        nid, label = r[0], r[1]
        db.execute("DELETE FROM edges WHERE pid=? AND (from_id=? OR to_id=?)",
                   (pid, nid, nid))
        db.execute("DELETE FROM nodes WHERE pid=? AND id=?", (pid, nid))
        db.execute("DELETE FROM node_hierarchy WHERE pid=? AND node_id=?", (pid, nid))
        if label:
            _cascade_delete_tag_refs(pid, label)
        deleted += 1
    db.commit()
    return f"Deleted {deleted} node(s) and their connections."


# ── Edge CRUD (Gap 1/2: no delete/update existed for a single edge) ────────

def _resolve_ids(pid: str, ref: str) -> list[str]:
    """A ref may be a unique node id or a (possibly duplicated) tag —
    returns every node id it could mean. Callers that need a SINGLE
    target should pass an id (e.g. from a Holistic-resolved pair) rather
    than relying on the first match here."""
    r = _find_node(pid, ref)
    return [r[0]] if r is not None else []


def delete_edges(pid: str, from_tag: str, to_tag: str) -> str:
    """Delete the edge(s) between two nodes, in either direction —
    tags/ids resolved the same way add_edges/update_node accept them.
    Mirrors Rust's delete_edge_by_id semantics (direct id match) when
    given ids; falls back to a first-match tag resolution otherwise, so
    callers holding a Holistic-resolved node id never hit ambiguity."""
    ra, rb = _find_node(pid, from_tag), _find_node(pid, to_tag)
    if ra is None:
        return f"ERROR: '{from_tag}' does not exist"
    if rb is None:
        return f"ERROR: '{to_tag}' does not exist"
    fid, tid = ra[0], rb[0]
    db = _db()
    cur = db.execute(
        "DELETE FROM edges WHERE pid=? AND ((from_id=? AND to_id=?) OR "
        "(from_id=? AND to_id=?))", (pid, fid, tid, tid, fid))
    if cur.rowcount:
        _unmirror_connection_between(pid, ra[1] or fid, rb[1] or tid)
    db.commit()
    if cur.rowcount == 0:
        return f"ERROR: no edge found between '{from_tag}' and '{to_tag}'"
    return f"Deleted {cur.rowcount} edge(s) between {from_tag} and {to_tag}."


def update_edge(pid: str, from_tag: str, to_tag: str,
                kind: str | None = None) -> str:
    """Reclassify an existing edge (e.g. stream -> signal, or add a
    bypass/recycle kind) without deleting and re-adding it — re-adding
    would mint a new edge row and lose any waypoints/bend data attached
    to the original."""
    if not kind:
        return "ERROR: nothing to update — pass a new kind"
    ra, rb = _find_node(pid, from_tag), _find_node(pid, to_tag)
    if ra is None:
        return f"ERROR: '{from_tag}' does not exist"
    if rb is None:
        return f"ERROR: '{to_tag}' does not exist"
    fid, tid = ra[0], rb[0]
    db = _db()
    cur = db.execute(
        "UPDATE edges SET kind=? WHERE pid=? AND ((from_id=? AND to_id=?) "
        "OR (from_id=? AND to_id=?))", (kind, pid, fid, tid, tid, fid))
    if cur.rowcount:
        # Mirror the reclassification into connections.type too — same
        # gap-fix family as add_edges/delete_edges, otherwise export_vids
        # would keep showing the edge's PRE-update type after a legitimate
        # reclassification (e.g. stream -> signal).
        tag_a, tag_b = ra[1] or fid, rb[1] or tid
        db.execute(
            "UPDATE connections SET type=? WHERE pid=? AND "
            "((from_tag=? AND to_tag=?) OR (from_tag=? AND to_tag=?))",
            (kind, pid, tag_a, tag_b, tag_b, tag_a))
    db.commit()
    if cur.rowcount == 0:
        return f"ERROR: no edge found between '{from_tag}' and '{to_tag}'"
    return f"Updated {cur.rowcount} edge(s) between {from_tag} and {to_tag} to kind={kind}."


# ── Proposal review (Gap 6/7: Pass-3 tag + Pass-4 connection queue) ────────

def list_proposals(pid: str, proposal_type: str | None = None) -> list[dict]:
    """Pending AI-inferred proposals awaiting engineer review (written by
    the extraction workflow's inference_agent.py — Pass 3 tag repairs/
    inference, Pass 4 connection proposals). Excludes already-resolved
    ones (review_state accepted/rejected)."""
    sql = ("SELECT node_id, type, original, proposed, confidence, method, "
           "review_state FROM proposals WHERE pid=? AND "
           "(review_state IS NULL OR review_state NOT IN "
           "('accepted','rejected'))")
    args: list = [pid]
    if proposal_type:
        sql += " AND type=?"
        args.append(proposal_type)
    rows = _db().execute(sql + " ORDER BY confidence DESC LIMIT 40",
                         args).fetchall()
    return [{"node_id": r[0], "type": r[1], "original": r[2],
            "proposed": r[3], "confidence": r[4], "method": r[5],
            "review_state": r[6] or "inferred"} for r in rows]


def review_proposal(pid: str, node_id: str, proposal_type: str,
                    accept: bool) -> str:
    """Accept applies the proposal to the graph (tag rename via
    update_node, or a new connection via add_edges) and marks it
    accepted; reject just marks it rejected — the extraction pipeline's
    own re-run logic already skips rejected proposals on rebuild."""
    db = _db()
    row = db.execute(
        "SELECT original, proposed FROM proposals WHERE pid=? AND "
        "node_id=? AND type=?", (pid, node_id, proposal_type)).fetchone()
    if row is None:
        return (f"ERROR: no {proposal_type} proposal found for "
                f"node_id='{node_id}'")
    original, proposed = row[0], row[1]

    if accept:
        if proposal_type == "tag":
            result = update_node(pid, node_id, new_tag=proposed)
            if result.startswith("ERROR"):
                return result
        elif proposal_type == "connection":
            result = add_edges(pid, [{"from_tag": node_id,
                                      "to_tag": proposed}])
            if result.startswith("ERROR"):
                return result
        else:
            return f"ERROR: unknown proposal type '{proposal_type}'"
        state = "accepted"
    else:
        state = "rejected"

    db.execute("UPDATE proposals SET review_state=? WHERE pid=? AND "
              "node_id=? AND type=?", (state, pid, node_id, proposal_type))
    db.commit()
    return (f"{'Accepted' if accept else 'Rejected'} {proposal_type} "
            f"proposal for {node_id} ({original!r} -> {proposed!r}).")


# ── Loop awareness (Gap 4/5: read-only control-loop status) ────────────────

def _espx_for_loops(pid: str) -> dict:
    db = _db()
    instruments = {}
    for tag, area, kind_detail, itype in db.execute(
            "SELECT tag, area, kind_detail, type FROM instruments "
            "WHERE pid=?", (pid,)).fetchall():
        instruments[tag] = {"area": area or "", "type": itype or kind_detail or ""}
    nodes = [{"id": r[0], "kind": r[1], "label": r[2]}
            for r in db.execute("SELECT id, kind, label FROM nodes "
                                "WHERE pid=?", (pid,)).fetchall()]
    # Controllers and transmitters authored as nodes are indexed as
    # instruments too, even when the instruments mirror has not caught up.
    for n in nodes:
        if _is_instrument_kind(n["kind"]) and n["label"] and n["label"] not in instruments:
            instruments[n["label"]] = {"area": "", "type": n["kind"]}
    return {"studio": {"instruments": instruments}, "nodes": nodes}


def get_loops(pid: str, status_filter: str | None = None) -> list[dict]:
    """Live control-loop inference from ISA tag matching (same algorithm
    the extraction workflow uses — domain/loop_inference.infer_loops) —
    computed fresh from the current graph, never a stale persisted copy,
    matching the grid system's "always rebuildable, never a second
    source of truth" principle.

    status_filter: "complete" | "incomplete" | "no_controller" | None"""
    try:
        from domain.loop_inference import infer_loops
    except Exception:
        return []
    loops = infer_loops(_espx_for_loops(pid))
    out = []
    for loop_id, rec in loops.items():
        if isinstance(rec, dict):
            status = rec.get("status", "")
            if status_filter and status != status_filter:
                continue
            out.append({"loop_id": loop_id, **rec})
    return out


def loop_members(loop: dict) -> set[str]:
    """Every tag a loop record names."""
    out = {loop.get(k) for k in ("controller", "measurement", "final_element")}
    for k in ("indicators", "alarms", "other"):
        out.update(loop.get(k) or [])
    return {t for t in out if t}


def check_loop_completeness(pid: str) -> dict:
    """Summary counts by status — the direct answer to "how many loops
    are missing a controller" style questions."""
    loops = get_loops(pid)
    buckets: dict[str, int] = {}
    for loop in loops:
        status = loop.get("status", "unknown")
        buckets[status] = buckets.get(status, 0) + 1
    return {"total": len(loops), "by_status": buckets}


def get_describe_session(pid: str, session_id: str) -> dict | None:
    try:
        row = _db().execute(
            "SELECT history_json, active_solution_json FROM describe_session_states WHERE pid=? AND session_id=?",
            (pid, str(session_id))).fetchone()
        if not row:
            return None
        return {
            "history": json.loads(row[0] or "[]"),
            "active_solution": json.loads(row[1]) if row[1] else None,
        }
    except Exception as e:
        print(f"[describe] WARNING: failed to get describe session: {e}")
        return None


def save_describe_session(pid: str, session_id: str, history: list[dict], active_solution: dict | None = None) -> None:
    try:
        import datetime as _dt
        ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')
        db = _db()
        db.execute(
            "INSERT INTO describe_session_states (pid, session_id, history_json, active_solution_json, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(pid, session_id) DO UPDATE SET "
            "history_json=excluded.history_json, active_solution_json=excluded.active_solution_json, updated_at=excluded.updated_at",
            (pid, str(session_id), json.dumps(history), json.dumps(active_solution) if active_solution else None, ts)
        )
        db.commit()
    except Exception as e:
        print(f"[describe] WARNING: failed to save describe session: {e}")


def clear_describe_session(pid: str, session_id: str) -> None:
    try:
        db = _db()
        db.execute("DELETE FROM describe_session_states WHERE pid=? AND session_id=?", (pid, str(session_id)))
        db.commit()
    except Exception:
        pass


# ── Plant hierarchy tools (systems and subsystems) ───────────────────────────

def list_hierarchy(pid: str) -> dict:
    """The project's plant hierarchy (site > plant > unit > area > system >
    subsystem) with node counts, plus how many nodes are unassigned."""
    from services import hierarchy as H
    return H.tree(pid)


def create_system(pid: str, system: str, area: str | None = None,
                  unit: str | None = None, plant: str | None = None,
                  site: str | None = None) -> str:
    """Create (or find) a system, creating any missing parent levels.
    Idempotent."""
    from services import hierarchy as H
    if not system:
        return "ERROR: system is required"
    try:
        hid = H.ensure_path(pid, {"site": site, "plant": plant, "unit": unit,
                                  "area": area, "system": system})
    except ValueError as exc:
        return f"ERROR: {exc}"
    path = " > ".join(v for v in H.path_of(pid, hid).values())
    return f"System ready: {path} (id {hid})."


def get_subsystem(pid: str, name: str, system: str | None = None) -> dict:
    """Look up a subsystem (or system) by name: its full path, node count and
    child groups. When the name matches several groups, returns every candidate
    so you can ask the engineer which one they mean."""
    from services import hierarchy as H
    hits = H.find(pid, name, level="subsystem", parent_name=system)
    if not hits:
        hits = [h for h in H.find(pid, name, parent_name=system)
                if h["level"] in ("subsystem", "system")]
    if not hits:
        return {"found": False, "known": _hierarchy_names(pid)}

    def _describe(h: dict) -> dict:
        children = _db().execute(
            "SELECT name, level FROM hierarchy WHERE pid=? AND parent_id=? ORDER BY name",
            (pid, h["id"])).fetchall()
        return {"id": h["id"], "name": h["name"], "level": h["level"],
                "path": H.path_of(pid, h["id"]), "nodes": len(H.contents(pid, h["id"])),
                "children": [{"name": c[0], "level": c[1]} for c in children]}

    if len(hits) == 1:
        return {"found": True, **_describe(hits[0])}
    return {"found": True, "ambiguous": True, "candidates": [_describe(h) for h in hits]}


def create_subsystem(pid: str, subsystem: str, system: str,
                     area: str | None = None, unit: str | None = None,
                     plant: str | None = None, site: str | None = None) -> str:
    """Create (or find) a subsystem under a system, creating any missing
    parent levels. Idempotent."""
    from services import hierarchy as H
    if not subsystem or not system:
        return "ERROR: both subsystem and system are required"
    try:
        existing = H.find(pid, system, level="system")
        exact = [h for h in existing if h["name"].lower() == " ".join(system.split()).lower()]
        if not any((site, plant, unit, area)) and len(exact) == 1:
            # The system already exists somewhere in the plant: hang the
            # subsystem under it rather than creating a second, rootless copy.
            hid = H.get_or_create(pid, "subsystem", subsystem, parent_id=exact[0]["id"])
        else:
            hid = H.ensure_path(pid, {"site": site, "plant": plant, "unit": unit,
                                      "area": area, "system": system,
                                      "subsystem": subsystem})
    except ValueError as exc:
        return f"ERROR: {exc}"
    path = " > ".join(v for v in H.path_of(pid, hid).values())
    return f"Subsystem ready: {path} (id {hid})."


def assign_to_subsystem(pid: str, tags: list[str], subsystem: str,
                        system: str | None = None) -> str:
    """Move existing nodes into a subsystem (or a system when subsystem names
    one)."""
    if not tags:
        return "ERROR: no tags given"
    rows = [(_find_node(pid, t), t) for t in tags]
    missing = [t for r, t in rows if r is None]
    if missing:
        return f"ERROR: tags do not exist: {missing}"
    group, err = _resolve_group(pid, subsystem, system)
    if err:
        return err
    note = _assign_to(pid, [r[0] for r, _ in rows], group)
    return f"Assigned {len(rows)} node(s){note}."


def get_subsystem_contents(pid: str, subsystem: str,
                           system: str | None = None) -> dict:
    """Nodes, tags and control loops inside a subsystem (including anything
    assigned to groups beneath it)."""
    from services import hierarchy as H
    group, err = _resolve_group(pid, subsystem, system)
    if err:
        return {"error": err}
    ids = H.contents(pid, group)
    nodes = []
    for nid in ids:
        r = _db().execute("SELECT id, label, kind FROM nodes WHERE pid=? AND id=?",
                          (pid, nid)).fetchone()
        if r:
            nodes.append({"id": r[0], "tag": r[1] or r[0], "kind": r[2]})
    tags = {n["tag"] for n in nodes}
    loops = [l for l in get_loops(pid) if tags & loop_members(l)]
    return {"path": H.path_of(pid, group), "nodes": nodes, "loops": loops}


def sync_hierarchy(pid: str, source: str = "areas", plant: str | None = None,
                   unit: str | None = None) -> str:
    """Seed the hierarchy. source="areas" groups digitised nodes by their area;
    source="inventory" imports site..subsystem from the asset inventory (when
    enabled) and assigns matching tags."""
    from services import hierarchy as H
    if source == "areas":
        res = H.bootstrap_from_areas(pid)
        return (f"Created {res['created']} area group(s) {res['areas']} and "
                f"assigned {res['assigned']} node(s).")
    if source == "inventory":
        res = H.sync_from_inventory(pid, plant=plant, unit=unit)
        if res.get("error"):
            return f"ERROR: {res['error']}"
        return (f"Imported {res['paths']} hierarchy path(s) from {res['assets']} "
                f"asset(s); assigned {res['assigned_nodes']} node(s).")
    return "ERROR: source must be 'areas' or 'inventory'"


# ── Tag numbering and instrument packages ────────────────────────────────────

_TAG_NUM_RE = re.compile(r"^([A-Z]{1,5})-0*(\d{1,6})([A-Z]?)$")


def _numbers_in_use(pid: str) -> dict[str, set[int]]:
    """prefix -> loop numbers used by existing tags."""
    used: dict[str, set[int]] = {}
    for (label,) in _db().execute("SELECT label FROM nodes WHERE pid=?", (pid,)).fetchall():
        m = _TAG_NUM_RE.match((label or "").upper())
        if m:
            used.setdefault(m.group(1), set()).add(int(m.group(2)))
    return used


def next_tag(pid: str, prefix: str, series: str | None = None) -> str:
    """The next free tag for an ISA prefix, following the plant's numbering.
    With series (e.g. "2041") returns PREFIX-2041, or PREFIX-2041A/B/... when
    taken."""
    prefix = (prefix or "").strip().upper().rstrip("-")
    if not re.match(r"^[A-Z]{1,5}$", prefix):
        return "ERROR: prefix must be 1-5 letters, e.g. PT"
    if series:
        base = f"{prefix}-{series}"
        if _find_node(pid, base) is None:
            return base
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if _find_node(pid, base + letter) is None:
                return base + letter
        return f"ERROR: no free suffix left for {base}"
    used = _numbers_in_use(pid)
    pool = used.get(prefix) or set().union(*used.values()) if used else set()
    n = (max(pool) + 1) if pool else 100
    while _find_node(pid, f"{prefix}-{n}") is not None:
        n += 1
    return f"{prefix}-{n}"


def _free_loop_number(pid: str, prefixes: list[tuple[str, str]], anchor_tag: str) -> str:
    """A loop number where every member tag (prefix + suffix) is free, starting
    just above the anchor's own number so new loops sit in its series."""
    m = _TAG_NUM_RE.match((anchor_tag or "").upper())
    used = _numbers_in_use(pid)
    width = len(m.group(2)) if m else 0
    start = int(m.group(2)) + 1 if m else \
        ((max(set().union(*used.values())) + 1) if used else 100)
    n = start
    while True:
        series = str(n).zfill(width)
        if all(_find_node(pid, f"{p}-{series}{s}") is None for p, s in prefixes):
            return series
        n += 1


def add_instrument_package(pid: str, package: str, anchor_tag: str,
                           subsystem: str | None = None, system: str | None = None,
                           tag_series: str | None = None, with_control: bool = False,
                           valve_between: list[str] | None = None,
                           direction: str | None = None) -> str:
    """Build a complete instrument package in one step, wired in the four-way
    topology (Acc-Acc, Acc-Inst, Inst-Inst, Inst-Acc).

    package: pressure | temperature | flow | level.
    anchor_tag: the existing tie-in (line, header, vessel) the package taps.
    with_control: also add controller, air regulator, positioner, actuator and
      control valve. valve_between=[tag_a, tag_b] puts the control valve inline
      in that existing line; without it the valve is added but not yet inline.
    tag_series: loop number (e.g. "2041"); chosen automatically when omitted.
    Existing tags are never reused and repeating the call never duplicates.
    """
    from services import instrument_packages as IP
    from services.placement import parse_direction, place_new_nodes

    package = (package or "").strip().lower()
    if package not in IP.PACKAGES:
        return f"ERROR: unknown package '{package}'. Available: {IP.names()}"
    anchor = _find_node(pid, anchor_tag)
    if anchor is None:
        return f"ERROR: anchor_tag '{anchor_tag}' does not exist"
    members = IP.members_for(package, bool(with_control))
    connections = IP.connections_for(package, bool(with_control))
    if valve_between is not None:
        if not isinstance(valve_between, list) or len(valve_between) != 2:
            return "ERROR: valve_between must be [tag_a, tag_b]"
        ra, rb = _find_node(pid, valve_between[0]), _find_node(pid, valve_between[1])
        if ra is None or rb is None:
            return f"ERROR: valve_between tag does not exist: {valve_between}"
    group, err = _resolve_group(pid, subsystem, system)
    if err:
        return err

    series = tag_series or _free_loop_number(
        pid, [(m.prefix, m.suffix) for m in members], anchor[1] or anchor[0])
    tag_of = {m.role: f"{m.prefix}-{series}{m.suffix}" for m in members}
    taken = [t for t in tag_of.values() if _find_node(pid, t) is not None]
    if taken:
        if tag_series and all(_find_node(pid, t) is not None for t in tag_of.values()):
            return (f"NOOP: the {package} package for loop {series} already exists "
                    f"({sorted(tag_of.values())}).")
        return (f"ERROR: tags already exist for loop {series}: {taken}. Omit "
                "tag_series to pick a free loop number.")

    anchor_ref = anchor[1] or anchor[0]
    inline_valve = next((m for m in members if m.inline), None)
    placement_edges = [((anchor_ref if a == "@anchor" else tag_of[a]),
                        (anchor_ref if b == "@anchor" else tag_of[b]))
                       for a, b, _ in connections]
    placed = place_new_nodes(_positions(pid), list(tag_of.values()), placement_edges,
                             parse_direction(direction) if direction else None,
                             anchor_tag=anchor_ref)
    area = anchor[4] or ""
    inherited = _inherit(pid, anchor_ref)
    db = _db()
    for m in members:
        if inline_valve is not None and m is inline_valve and valve_between:
            continue                                  # inserted inline below
        tag = tag_of[m.role]
        x, y = placed[tag]
        extra = {"description": m.description, "package": package,
                 "package_role": m.role, "loop": series, **inherited,
                 **_spec_fields(tag, {})}
        db.execute(
            "INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y,"
            " extra_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (tag, pid, m.kind, m.kind, tag, area, x, y, _authored_json(extra)))
        _mirror_node_to_instrument_or_equipment(pid, tag, m.kind, area)
    db.commit()

    warnings = []
    if inline_valve is not None:
        vtag = tag_of[inline_valve.role]
        if valve_between:
            res = break_line(pid, valve_between[0], valve_between[1],
                             {"tag": vtag, "kind": inline_valve.kind,
                              "description": inline_valve.description})
            if res.startswith("ERROR"):
                res2 = insert_between(pid, {"tag": vtag, "kind": inline_valve.kind,
                                             "description": inline_valve.description},
                                      valve_between[0], valve_between[1])
                if res2.startswith("ERROR"):
                    return res2
                warnings.append(f"{valve_between[0]} and {valve_between[1]} were not "
                                f"connected; {vtag} now joins them")
        else:
            warnings.append(f"{vtag} is not inline yet: call break_line with the "
                            "process line it belongs in")

    added = 0
    for a, b, kind in connections:
        f_row = anchor if a == "@anchor" else _find_node(pid, tag_of[a])
        t_row = anchor if b == "@anchor" else _find_node(pid, tag_of[b])
        if f_row is not None and t_row is not None and _insert_edge(pid, f_row, t_row, kind):
            added += 1
    db.commit()
    note = _assign_to(pid, [tag_of[m.role] for m in members], group,
                      fallback_from=anchor_ref)
    warn = f" Warnings: {warnings}." if warnings else ""
    return (f"Built {package} package, loop {series}, at {anchor_ref}: "
            f"{sorted(tag_of.values())}; {added} connection(s){note}.{warn}")


def digitisation_status(pid: str) -> dict:
    """Whether the project holds a digitised drawing a retrofit can build on."""
    db = _db()
    total = db.execute("SELECT COUNT(*) FROM nodes WHERE pid=?", (pid,)).fetchone()[0]
    try:
        authored = db.execute("SELECT COUNT(*) FROM nodes WHERE pid=? AND origin='authored'",
                              (pid,)).fetchone()[0]
    except Exception:                    # hub not migrated yet: read the marker itself
        authored = db.execute(
            "SELECT COUNT(*) FROM nodes WHERE pid=? AND (extra_json LIKE ? OR extra_json LIKE ?)",
            (pid, '%"origin": "authored"%', '%"origin":"authored"%')).fetchone()[0]
    try:
        lines = db.execute("SELECT COUNT(*) FROM geometry_lines WHERE pid=?",
                           (pid,)).fetchone()[0]
    except Exception:
        lines = 0
    extracted = total - authored
    return {"digitised": extracted > 0, "extracted_nodes": extracted,
            "authored_nodes": authored, "geometry_lines": lines}


def analyze_uploaded_pid(pid: str, image_path: str | None = None) -> str:
    """Read the uploaded P&ID with the vision model (tiled and verified) without writing anything.

    Returns a short summary; the full reading is cached so rebuild_digital_pid
    persists exactly what was read instead of calling the model again.
    """
    from domain.solution.services.brownfield_vision_service import (
        analyze_uploaded_pid as _analyze, summarize_analysis)
    return summarize_analysis(_analyze(pid=pid, image_path=image_path))


def rebuild_digital_pid(pid: str, user_id: int | None = 1, refresh: bool = False) -> str:
    """Persist the drawing reading as the project's digital P&ID graph (reads the drawing first if needed).

    Refuses (NOOP) when the project is already digitised unless refresh=True,
    because a rebuild replaces every extracted node, including what refine added.
    """
    if not refresh and digitisation_status(pid).get("digitised"):
        return ("NOOP: this project is already digitised; rebuilding would replace it. "
                "Pass refresh=true only if the engineer asked to re-read the drawing.")
    from domain.solution.services.brownfield_vision_service import rebuild_digital_pid as _rebuild
    res = _rebuild(pid=pid, user_id=user_id)
    if "error" in res:
        return res["error"]
    return res.get("summary", f"Rebuilt digital P&ID {pid} successfully.")


def digitise_uploaded_pid(pid: str, refresh: bool = False) -> str:
    """Read the uploaded drawing, rebuild it as the digital P&ID and score it, in one step.

    refresh=True re-reads the drawing even when a reading of the same file is cached.
    """
    from domain.solution.services.brownfield_vision_service import (
        analyze_uploaded_pid as _analyze, rebuild_digital_pid as _rebuild)
    analysis = _analyze(pid=pid, use_cache=not refresh)
    if analysis.get("error"):
        return analysis["error"]
    res = _rebuild(pid=pid, analysis=analysis)
    if "error" in res:
        return res["error"]
    parts = [res.get("summary", "")]
    try:
        from domain.solution.services.pid_accuracy_service import evaluate_intrinsic_accuracy
        ev = evaluate_intrinsic_accuracy(pid, save_local=False)
        parts.append(f"Graph quality {ev.get('accuracy_score')} ({ev.get('rating')}).")
        issues = ev.get("issues") or []
        if issues:
            parts.append("Open issues: " + "; ".join(str(i) for i in issues[:4]) + ".")
    except Exception as exc:
        parts.append(f"(quality check unavailable: {str(exc)[:120]})")
    st = analysis.get("stats") or {}
    if st:
        parts.append(f"Read in {st.get('tiles')} tiles with {st.get('calls')} model calls "
                     f"in {st.get('seconds')}s.")
    return " ".join(p for p in parts if p)


def evaluate_pid_accuracy(pid: str, agent_type: str = "general") -> dict:
    """Evaluate engineering accuracy, ISA tag compliance, loop completeness, and orphan rates.

    Saves evaluation to local files and returns composite accuracy score, metric breakdown, and prompt refinement guidance.
    """
    from domain.solution.services.pid_accuracy_service import evaluate_intrinsic_accuracy
    return evaluate_intrinsic_accuracy(pid, save_local=True, agent_type=agent_type)


def get_accuracy_history(pid: str | None = None, limit: int = 50) -> list[dict]:
    """Retrieve historical accuracy evaluation records from local JSONL storage."""
    from domain.solution.services.pid_accuracy_service import get_accuracy_history as _get_hist
    return _get_hist(pid=pid, limit=limit)


def analyze_accuracy_history() -> dict:
    """Analyze all stored local accuracy metrics, cross-project failure distributions, and generate improvement recommendations."""
    from domain.solution.services.pid_accuracy_service import analyze_stored_accuracy_metrics
    return analyze_stored_accuracy_metrics()


def refine_pid_drawing(pid: str) -> str:
    """Execute diagnostic-guided prompt re-analysis using Qwen3-VL to resolve missing elements and improve accuracy."""
    from domain.solution.services.pid_accuracy_service import refine_and_reanalyze
    res = refine_and_reanalyze(pid)
    if "error" in res:
        return res["error"]
    return res.get("summary", f"Refinement completed for {pid}.")




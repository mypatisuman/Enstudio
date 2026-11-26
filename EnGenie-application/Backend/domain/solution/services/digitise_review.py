"""Guided review of a digitised P&ID: the last step to 100%.

No vision model reads every drawing perfectly, so the digitiser says where it
is unsure, and the engineer settles exactly those items:

    tag      read but not certain: inferred valves, untagged symbols, tags
             corrected from the loop numbering, re-read in a close-up, rescued
             by the second look, or left unchecked when a check call failed
    link     traced but not certain: seen by only one of the two readings,
             or added by an engineering rule rather than traced
    missing  where something was probably NOT found: a symbol with no
             connection, equipment with no process line, a control loop
             whose controller is not connected to its loop

Each item carries a stable id (kind + reason + tags), so a decision survives
re-digitising the same drawing. Decisions are applied to the graph (studio.db)
through the describe repository and kept in pid_review_items; re-digitising
re-applies them (rejected tags and links stay removed, renames stay renamed).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

logger = logging.getLogger(__name__)

#: code -> (kind, confidence shown to the engineer). Lower confidence = review first.
CODES = {
    "inferred": ("tag", 0.55),
    "loop_corrected": ("tag", 0.6),
    "untagged": ("tag", 0.65),
    "repaired": ("tag", 0.7),
    "second_look": ("tag", 0.7),
    "unchecked": ("tag", 0.75),
    "placeholder": ("tag", 0.75),
    "single_read": ("tag", 0.85),
    "orphan": ("missing", 0.5),
    "no_process_line": ("missing", 0.55),
    "loop_unconnected": ("missing", 0.6),
    "rule": ("link", 0.7),
    "one_model": ("link", 0.72),
    "single_view": ("link", 0.75),
}
SIGNAL_KINDS = {"signal", "pneumatic", "electrical", "software", "data", "capillary"}

_DDL = """
CREATE TABLE IF NOT EXISTS pid_review_items (
  pid           TEXT,
  item_id       TEXT,
  kind          TEXT,
  code          TEXT,
  tags_json     TEXT,
  reason        TEXT,
  confidence    REAL,
  status        TEXT,
  decision_json TEXT,
  updated_at    TEXT,
  PRIMARY KEY (pid, item_id)
);
"""


def _item(code: str, tags: list[str], reason: str, **extra) -> dict:
    kind, conf = CODES[code]
    key = f"{kind}|{code}|{'|'.join(sorted(tags))}"
    return {"id": hashlib.sha1(key.encode("utf-8")).hexdigest()[:12], "kind": kind, "code": code,
            "tags": list(tags), "reason": reason, "confidence": conf, **extra}


def build_review_queue(objects: list[dict], edges: list[tuple[str, str, str]], stats: dict,
                       loops: list[dict] | None = None, *, include_single_reads: bool = False) -> list[dict]:
    """The items the engineer should settle, least certain first."""
    items: list[dict] = []
    tags = {o["tag"] for o in objects}
    kind_of = {o["tag"]: o.get("node_kind", "") for o in objects}
    for o in objects:
        t = o["tag"]
        if o.get("inferred"):
            items.append(_item("inferred", [t], f"{t} is not printed as a tag: it was inferred from its loop "
                                                f"and the note '{o.get('note') or o.get('raw') or ''}'. Confirm it."))
        elif o.get("untagged"):
            items.append(_item("untagged", [t], f"{t} is an untagged symbol ({o.get('kind_detail') or kind_of[t]}): "
                                                "confirm what it is."))
        elif o.get("placeholder"):
            items.append(_item("placeholder", [t], f"{t} is a template placeholder tag: give it its real tag."))
        elif o.get("check") == "second_look":
            items.append(_item("second_look", [t], f"{t} was rejected by the first check and accepted on a "
                                                   "close-up: confirm it is printed there."))
        elif o.get("check") == "unchecked":
            items.append(_item("unchecked", [t], f"{t} could not be checked (the check call failed): "
                                                 "confirm it is printed there."))
        elif include_single_reads and o.get("check") == "transcription" and kind_of[t] != "tie_in":
            items.append(_item("single_read", [t], f"{t} was read once and confirmed once: a quick look."))
    for fix in stats.get("inferred_tags") or []:
        if fix.get("inferred") in tags:
            items.append(_item("loop_corrected", [fix["inferred"]],
                               f"The drawing reads '{fix.get('read')}'; it was corrected to {fix['inferred']} "
                               "from the loop numbering. Confirm the tag."))
    for t in stats.get("repaired_tags") or []:
        if t in tags:
            items.append(_item("repaired", [t], f"{t}: its letters were missing in the first reading and "
                                                "re-read in a close-up. Confirm the tag."))

    # links
    seen_by = stats.get("_seen_by") or {}
    rule_added = stats.get("_rule_added") or {}
    model_votes = stats.get("_model_votes") or {}          # set when two models traced the links
    connected: dict[str, set[str]] = {}
    process: set[str] = set()
    for a, b, k in edges:
        key = (a, b) if a < b else (b, a)
        connected.setdefault(a, set()).add(b)
        connected.setdefault(b, set()).add(a)
        if k not in SIGNAL_KINDS:
            process.update((a, b))
        if key in rule_added:
            items.append(_item("rule", list(key), f"{a} - {b} was added by the {rule_added[key]}, not traced "
                                               "on the drawing. Confirm the link.", link=[a, b, k]))
        elif model_votes and model_votes.get(key, 0) < 2:
            items.append(_item("one_model", list(key), f"{a} - {b} was traced by only one of the two connection "
                                                        "models. Confirm the link.", link=[a, b, k]))
        elif seen_by.get(key) == 1:
            items.append(_item("single_view", list(key), f"{a} - {b} was traced by only one of the two readings. "
                                                      "Confirm the link.", link=[a, b, k]))

    # probably missing
    for o in objects:
        t = o["tag"]
        if t not in connected and kind_of[t] != "junction":
            items.append(_item("orphan", [t], f"No connection was traced to {t}. Add what it connects to, "
                                              "or confirm it stands alone."))
        elif kind_of[t] in _EQUIPMENT and t not in process:
            items.append(_item("no_process_line", [t], f"{t} has no process line traced in or out. Add its "
                                                       "lines, or confirm."))
    for lp in loops or []:
        members = [m for m in lp.get("members") or [] if m in tags]
        ctrl = [m for m in members if (kind_of.get(m) == "controller")]
        for c in ctrl:
            if not (connected.get(c, set()) & set(members)):
                items.append(_item("loop_unconnected", [c] + [m for m in members if m != c],
                                   f"Loop {lp.get('loop_id')}: the controller {c} is not connected to any other "
                                   f"member ({', '.join(m for m in members if m != c)}). Add its signal lines, "
                                   "or confirm."))
    seen, out = set(), []
    for it in sorted(items, key=lambda i: (i["confidence"], i["tags"])):
        if it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out


_EQUIPMENT = {"vessel", "tank", "column", "pump", "compressor", "heat_exchanger", "exchanger", "reactor", "filter",
              "mixer", "equipment"}


# ── storage and decisions ───────────────────────────────────────────────────

def _db():
    from adapters.db import get_db
    db = get_db()
    db.executescript(_DDL)
    return db


def store_queue(pid: str, items: list[dict]) -> dict:
    """Replace the drawing's open items with `items`; decided items keep their
    decision (a re-digitised drawing does not ask the same question twice)."""
    db = _db()
    decided = {r[0] for r in db.execute(
        "SELECT item_id FROM pid_review_items WHERE pid=? AND status != 'pending'", (pid,))}
    db.execute("DELETE FROM pid_review_items WHERE pid=? AND status='pending'", (pid,))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    added = 0
    for it in items:
        if it["id"] in decided:
            continue
        db.execute("INSERT OR REPLACE INTO pid_review_items (pid, item_id, kind, code, tags_json, reason, confidence, "
                   "status, decision_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (pid, it["id"], it["kind"], it["code"], json.dumps({"tags": it["tags"], "link": it.get("link")}),
                    it["reason"], it["confidence"], "pending", None, now))
        added += 1
    db.commit()
    return {"open": added, "already_decided": len(decided)}


def list_queue(pid: str, status: str | None = None) -> dict:
    db = _db()
    sql = "SELECT item_id, kind, code, tags_json, reason, confidence, status, decision_json FROM pid_review_items WHERE pid=?"
    args: list = [pid]
    if status:
        sql += " AND status=?"
        args.append(status)
    rows = db.execute(sql + " ORDER BY status != 'pending', confidence, item_id", args).fetchall()
    items = []
    for iid, kind, code, tj, reason, conf, st, dj in rows:
        t = json.loads(tj or "{}")
        items.append({"id": iid, "kind": kind, "code": code, "tags": t.get("tags") or [], "link": t.get("link"),
                      "reason": reason, "confidence": conf, "status": st,
                      "decision": json.loads(dj) if dj else None})
    counts: dict[str, int] = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return {"items": items, "counts": counts}


def _apply(pid: str, item: dict, action: str, correction: dict) -> str:
    """Make the decision true on the graph. Returns what was done."""
    from agents.describe.services import repository as R
    tags, link = item.get("tags") or [], item.get("link")
    if action == "confirm":
        return "kept as read"
    if action == "reject":
        if item["kind"] == "link" and link:
            return R.delete_edges(pid, link[0], link[1])
        if item["kind"] == "tag" and tags:
            return R.delete_nodes(pid, tags[:1], reason="rejected in the digitisation review")
        return "nothing to remove"
    if action == "rename":
        new = str(correction.get("tag") or "").strip().upper()
        if not new or not tags:
            return "ERROR: a new tag is required"
        return R.update_node(pid, tags[0], new_tag=new)
    if action == "add_link":
        a, b = str(correction.get("from") or "").strip(), str(correction.get("to") or "").strip()
        if not a or not b:
            return "ERROR: both ends of the link are required"
        return R.add_edges(pid, [{"from_tag": a, "to_tag": b, "kind": correction.get("kind") or "stream"}])
    if action == "remove_link":
        a, b = str(correction.get("from") or "").strip(), str(correction.get("to") or "").strip()
        return R.delete_edges(pid, a, b) if a and b else "ERROR: both ends of the link are required"
    return f"ERROR: unknown action '{action}'"


_STATUS = {"confirm": "confirmed", "reject": "rejected", "rename": "corrected", "add_link": "corrected",
           "remove_link": "corrected"}


def resolve(pid: str, item_id: str, action: str, correction: dict | None = None) -> dict:
    """The engineer's decision on one item, applied to the graph and kept."""
    correction = correction or {}
    queue = {it["id"]: it for it in list_queue(pid)["items"]}
    item = queue.get(item_id)
    if not item:
        return {"error": f"no review item {item_id}"}
    result = _apply(pid, item, action, correction)
    if isinstance(result, str) and result.startswith("ERROR"):
        return {"error": result}
    db = _db()
    db.execute("UPDATE pid_review_items SET status=?, decision_json=?, updated_at=? WHERE pid=? AND item_id=?",
               (_STATUS.get(action, "corrected"), json.dumps({"action": action, "correction": correction,
                                                              "result": str(result)[:300]}),
                time.strftime("%Y-%m-%dT%H:%M:%S"), pid, item_id))
    db.commit()
    return {"id": item_id, "status": _STATUS.get(action, "corrected"), "result": result}


def reapply_decisions(pid: str) -> int:
    """After re-digitising: rejected tags / links removed again, renames redone.
    Links the engineer added are authored rows and survive by themselves."""
    n = 0
    for it in list_queue(pid)["items"]:
        d = it.get("decision") or {}
        if it["status"] == "pending" or d.get("action") not in ("reject", "rename", "remove_link"):
            continue
        try:
            res = _apply(pid, it, d["action"], d.get("correction") or {})
            n += not str(res).startswith("ERROR")
        except Exception as exc:
            logger.debug("[review] re-applying %s failed: %s", it["id"], exc)
    return n

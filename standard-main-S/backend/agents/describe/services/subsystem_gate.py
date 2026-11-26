"""Subsystem clarification for brownfield retrofits.

Runs in the Describe workflow after the Holistic gate and before a brownfield
turn is dispatched. It decides, without a model call, whether the engineer has
to say which subsystem a retrofit goes into:

  named, one match        -> proceed; the dispatch message names the group
  named, several matches  -> ask which one (e.g. two "Feed" subsystems)
  named, no match         -> proceed; the agent may create it
  not named               -> ask, but only when the request adds equipment,
                             the project has subsystems to choose from, and
                             no tag in the message already sits in one (a
                             package defaults to its anchor's group)

The question and its candidates persist in describe_pending with
kind="subsystem", so the answer can arrive in a later process, exactly like
the Holistic gate's tag disambiguation.
"""
from __future__ import annotations

import re

KIND = "subsystem"

_BUILD_WORDS = re.compile(
    r"\b(add|adding|install|insert|retrofit\s+(?:a|an|the\s+new|new)|new|package|"
    r"tie[- ]?in|build|put)\b", re.IGNORECASE)
_TAG = re.compile(r"\b[A-Z]{1,5}-\d{1,6}[A-Z]?\b")
_GROUP_WORD = re.compile(r"\b(sub-?system|system)s?\b", re.IGNORECASE)
_QUOTED_AFTER = re.compile(
    r"\b(sub-?system|system)\s+(?:named|called)?\s*[\"'“‘](.+?)[\"'”’]", re.IGNORECASE)
_STOP = {"to", "in", "into", "under", "within", "for", "of", "on", "at", "the", "a",
         "an", "and", "with", "from", "this", "that", "its", "their", "existing",
         "same", "each", "every", "any", "which", "what"}
_NONE_REPLY = re.compile(
    r"^\s*(none|no|no subsystem|unassigned|leave it( unassigned)?|skip|neither|"
    r"don'?t assign|do not assign)\s*[.!]?\s*$", re.IGNORECASE)
_NUMBER_REPLY = re.compile(r"^\s*(?:option|choice|number|#)?\s*(\d+)\s*\.?\s*$", re.IGNORECASE)


def named_groups(message: str) -> dict[str, str]:
    """{"subsystem": name, "system": name} for groups the message names.

    "into the Feed Supply Header subsystem of the Hydrocarbon Ingress system"
    -> both. Names are the words just before the level word, back to the
    nearest preposition or article, or a quoted name just after it.
    """
    out: dict[str, str] = {}
    for m in _QUOTED_AFTER.finditer(message):
        level = "subsystem" if m.group(1).lower().startswith("sub") else "system"
        out.setdefault(level, m.group(2).strip())
    for m in _GROUP_WORD.finditer(message):
        level = "subsystem" if m.group(1).lower().startswith("sub") else "system"
        if level in out:
            continue
        words = re.findall(r"[\w\-/&']+", message[:m.start()])
        name: list[str] = []
        for w in reversed(words):
            if w.lower() in _STOP or len(name) == 6:
                break
            name.insert(0, w)
        if name and not all(_TAG.fullmatch(w) for w in name):
            out[level] = " ".join(name)
    return out


def _subsystems(pid: str) -> list[dict]:
    from services import hierarchy as H
    rows = H._db().execute(
        "SELECT h.id, h.name, p.name FROM hierarchy h LEFT JOIN hierarchy p "
        "ON p.id = h.parent_id AND p.pid = h.pid WHERE h.pid=? AND h.level='subsystem' "
        "ORDER BY p.name, h.name", (pid,)).fetchall()
    return [_candidate(pid, r[0], r[1], r[2]) for r in rows]


def _candidate(pid: str, hid: int, name: str, parent: str | None) -> dict:
    from services import hierarchy as H
    path = H.path_of(pid, hid)
    return {"hierarchy_id": hid, "name": name, "system": path.get("system") or parent,
            "path": " › ".join(path[level] for level in H.LEVELS if level in path)}


def _tag_already_grouped(pid: str, message: str) -> bool:
    from agents.describe.services import repository as R
    from services import hierarchy as H
    for tag in _TAG.findall(message):
        row = R._find_node(pid, tag)
        if row is not None and H.node_assignment(pid, row[0]).get("subsystem"):
            return True
    return False


def check(pid: str, message: str) -> dict:
    """{"status": "proceed", "note": str|None} or
    {"status": "ask", "question": str, "candidates": [...], "reason": str}."""
    from services import hierarchy as H
    named = named_groups(message)
    if named.get("subsystem"):
        hits = H.find(pid, named["subsystem"], level="subsystem",
                      parent_name=named.get("system"))
        if len(hits) == 1:
            return {"status": "proceed",
                    "note": dispatch_note(_candidate(pid, hits[0]["id"], hits[0]["name"],
                                                     hits[0]["parent"]))}
        if len(hits) > 1:
            cands = [_candidate(pid, h["id"], h["name"], h["parent"]) for h in hits]
            return {"status": "ask", "reason": "ambiguous", "candidates": cands,
                    "question": question(cands, f"More than one subsystem is called "
                                                f"'{named['subsystem']}'.")}
        return {"status": "proceed", "note": None}
    if named.get("system"):
        return {"status": "proceed", "note": None}
    if not _BUILD_WORDS.search(message):
        return {"status": "proceed", "note": None}
    cands = _subsystems(pid)
    if not cands or _tag_already_grouped(pid, message):
        return {"status": "proceed", "note": None}
    return {"status": "ask", "reason": "missing", "candidates": cands,
            "question": question(cands, "This project is organised into subsystems, and "
                                        "the request doesn't say which one the new "
                                        "equipment belongs to.")}


def question(candidates: list[dict], lead: str) -> str:
    lines = [lead, "Which subsystem should it go into?"]
    lines += [f"{i}. {c['path']}" for i, c in enumerate(candidates, 1)]
    lines.append("Reply with a number or a name, or 'none' to leave it unassigned.")
    return "\n".join(lines)


def dispatch_note(candidate: dict | None) -> str:
    if candidate is None:
        return ("\n\n[Plant group: the engineer chose to leave the new equipment "
                "unassigned. Do not pass subsystem or system.]")
    system = candidate.get("system")
    args = f'subsystem="{candidate["name"]}"' + (f', system="{system}"' if system else "")
    return (f"\n\n[Plant group confirmed: {candidate['path']}. "
            f"Pass {args} to every write tool that accepts them.]")


def interpret(reply: str, candidates: list[dict]) -> tuple[str, dict | None]:
    """("select", candidate) | ("none", None) | ("unclear", None)."""
    if _NONE_REPLY.match(reply):
        return "none", None
    m = _NUMBER_REPLY.match(reply)
    if m:
        idx = int(m.group(1)) - 1
        return ("select", candidates[idx]) if 0 <= idx < len(candidates) else ("unclear", None)
    text = " ".join(reply.lower().split())
    for key in ("path", "name", "system"):
        hits = [c for c in candidates if c.get(key) and c[key].lower() in text]
        # "Feed Supply Header" also contains "Feed": the longer name wins.
        hits = [c for c in hits if not any(o is not c and c[key].lower() in o[key].lower()
                                           and c[key].lower() != o[key].lower() for o in hits)]
        if len(hits) == 1:
            return "select", hits[0]
    hits = [c for c in candidates if text and text in c["path"].lower()]
    if len(hits) == 1:
        return "select", hits[0]
    return "unclear", None

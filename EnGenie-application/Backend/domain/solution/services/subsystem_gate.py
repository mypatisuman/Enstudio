"""
subsystem_gate.py - which subsystem does a retrofit go into?

Ported from the enSTUDIO Describe workflow (standard-main-S). Before a
modification of an existing P&ID is applied, this decides without a model call
whether the engineer has to say which subsystem the new equipment belongs to:

  named, one match        -> proceed; the request is annotated with the group
  named, several matches  -> ask which one
  named, no match         -> proceed; the agent may create it
  not named               -> ask, but only when the request adds equipment, the
                             drawing has two or more process subsystems to
                             choose from, and no tag in the request already
                             sits in one (a package defaults to its anchor's
                             group)

With exactly one process subsystem there is nothing to choose, so the request
proceeds into it. The -S gate asked even then; here that would be a question
with one answer.

The question is stored with the persisted P&ID as its pending_action and
answered through POST /api/pid/clarify, so the answer can arrive in any later
request, in any process.
"""

from __future__ import annotations

import re
from typing import Any

from domain.solution.services.pid_graph_store import PIDGraphStore

KIND = "subsystem_choice"

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
_NUMBER_REPLY = re.compile(r"^\s*(?:option|choice|number|#)?\s*(\d+)\s*\.?\s*$",
                           re.IGNORECASE)


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


def candidates(store: PIDGraphStore) -> list[dict[str, Any]]:
    """The drawing's process subsystems, in a stable order.

    A group made only of controllers is a DCS cabinet (the old generators put
    every controller in an area called PNL-01 or PNL-100), not a place process
    equipment can go, so it is not offered."""
    out = []
    for name, rec in sorted(store.hierarchy.items()):
        if rec.get("level", "subsystem") != "subsystem":
            continue
        members = [n for n in store.nodes if str(n.get("area") or "") == name]
        if members and all(str(n.get("kind")) == "controller" for n in members):
            continue
        system = rec.get("system")
        out.append({"name": name, "system": system,
                    "path": "%s › %s" % (system, name) if system else name,
                    "nodes": len(members)})
    return out


def _tag_already_grouped(store: PIDGraphStore, message: str) -> bool:
    for tag in _TAG.findall(message):
        node = store._find(tag)
        if node is not None and str(node.get("area") or ""):
            return True
    return False


def check(store: PIDGraphStore, message: str) -> dict[str, Any]:
    """{"status": "proceed", "note": str|None, "candidate": dict?} or
    {"status": "ask", "question": str, "candidates": [...], "reason": str}."""
    cands = candidates(store)
    named = named_groups(message or "")
    if named.get("subsystem"):
        want = named["subsystem"].lower()
        hits = [c for c in cands if c["name"].lower() == want] or \
               [c for c in cands if want in c["name"].lower()]
        if len(hits) == 1:
            return {"status": "proceed", "note": dispatch_note(hits[0]),
                    "candidate": hits[0]}
        if len(hits) > 1:
            return {"status": "ask", "reason": "ambiguous", "candidates": hits,
                    "question": question(hits, "More than one subsystem matches '%s'."
                                         % named["subsystem"])}
        return {"status": "proceed", "note": None}
    if named.get("system"):
        return {"status": "proceed", "note": None}
    if not _BUILD_WORDS.search(message or ""):
        return {"status": "proceed", "note": None}
    if not cands or _tag_already_grouped(store, message):
        return {"status": "proceed", "note": None}
    if len(cands) == 1:
        return {"status": "proceed", "note": dispatch_note(cands[0]),
                "candidate": cands[0]}
    return {"status": "ask", "reason": "missing", "candidates": cands,
            "question": question(cands, "This P&ID is organised into subsystems, and "
                                        "the request doesn't say which one the new "
                                        "equipment belongs to.")}


def question(cands: list[dict[str, Any]], lead: str) -> str:
    lines = [lead, "Which subsystem should it go into?"]
    lines += ["%d. %s" % (i, c["path"]) for i, c in enumerate(cands, 1)]
    lines.append("Reply with a number or a name, or 'none' to leave it unassigned.")
    return "\n".join(lines)


def dispatch_note(candidate: dict[str, Any] | None) -> str:
    """The annotation appended to the request the agent receives."""
    if candidate is None:
        return ("\n\n[Plant group: the engineer chose to leave the new equipment "
                "unassigned. Do not pass subsystem.]")
    return ("\n\n[Plant group confirmed: %s. Pass subsystem=\"%s\" to every write "
            "tool that accepts it.]" % (candidate["path"], candidate["name"]))


def interpret(reply: str, cands: list[dict[str, Any]]) -> tuple[str, dict | None]:
    """("select", candidate) | ("none", None) | ("unclear", None)."""
    if _NONE_REPLY.match(reply or ""):
        return "none", None
    m = _NUMBER_REPLY.match(reply or "")
    if m:
        idx = int(m.group(1)) - 1
        return ("select", cands[idx]) if 0 <= idx < len(cands) else ("unclear", None)
    text = " ".join((reply or "").lower().split())
    for key in ("path", "name", "system"):
        hits = [c for c in cands if c.get(key) and c[key].lower() in text]
        # "Feed Supply Header" also contains "Feed": the longer name wins.
        hits = [c for c in hits if not any(
            o is not c and c[key].lower() in o[key].lower()
            and c[key].lower() != o[key].lower() for o in hits)]
        if len(hits) == 1:
            return "select", hits[0]
    hits = [c for c in cands if text and text in c["path"].lower()]
    if len(hits) == 1:
        return "select", hits[0]
    return "unclear", None

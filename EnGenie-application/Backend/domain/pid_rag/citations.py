"""Checks the tags an answer cites against the drawing.

Answers cite tags as [TAG]. A cited tag that is not on the drawing is an
invention: its brackets are removed and the engineer is told, so a made-up
tag can never look like a drawing reference.
"""
from __future__ import annotations

import re

CITE_RE = re.compile(r"\[([A-Z0-9][A-Z0-9/._-]{1,40})\]")


def check_citations(reply: str, known_tags: set[str]) -> dict:
    """{"reply": cleaned reply, "citations": cited tags on the drawing (in order),
    "unknown": cited tags that are not on the drawing}."""
    by_upper = {t.upper(): t for t in known_tags}
    cited, unknown = [], []
    for m in CITE_RE.finditer(reply or ""):
        raw = m.group(1)
        t = by_upper.get(raw.upper())
        if t:
            if t not in cited:
                cited.append(t)
        elif raw not in unknown and re.search(r"[A-Z]-?\d|-[A-Z]", raw):
            unknown.append(raw)
    text = reply or ""
    for raw in unknown:
        text = text.replace(f"[{raw}]", raw)
    if unknown:
        text += ("\n\nNote: " + ", ".join(unknown) + (" is" if len(unknown) == 1 else " are")
                 + " not on this drawing.")
    return {"reply": text, "citations": cited, "unknown": unknown}

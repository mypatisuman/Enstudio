"""
services/placement.py — where a newly authored node goes on the sheet.

WHY THIS EXISTS
---------------
Digitised drawings store node positions as normalised 0-1 fractions of the
sheet. The Describe agents' write tools used to place new nodes with pixel-style
offsets -- `x + 140`, `100 + 140 * (n % 8)` -- so every brownfield addition
landed hundreds of sheet-widths outside the drawing, and the canvas's
fit-to-view zoomed out until the real drawing was a dot.

The desktop Describe screen already solved this correctly in
`frontend/src/domain/layout/placement.ts`. This module is a faithful port of
that algorithm, so the agent path and the client-side path place nodes the same
way:

* stay in the project's coordinate space and clamp to it;
* place a new node next to the existing node it connects to;
* try right, below, above, left, then diagonals, and take the first spot clear
  of every other node, or the roomiest if none is fully clear;
* honour an explicit side from the engineer's message ("left of", "below").

One deliberate extension: when a project was stored in pixel space (a legacy
canvas project), offsets scale to that extent instead of assuming 0-1, so the
same code is correct for both.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

#: Gap between a new node and its anchor, as a fraction of the sheet. Matched
#: to the spacing observed between extracted equipment/instrument pairs.
NEW_NODE_OFFSET = 0.055
#: A candidate closer than this to any existing node counts as occupied.
MIN_CLEARANCE = 0.03

#: Closest-fit first: right, below, above, left, then the four diagonals.
#: Left-to-right is standard P&ID flow.
PLACEMENT_DIRECTIONS = (
    (1, 0), (0, 1), (0, -1), (-1, 0),
    (1, 1), (-1, 1), (1, -1), (-1, -1),
)

Point = tuple[float, float]


class SheetSpace:
    """The coordinate space a project is stored in.

    `extent` is 1.0 for normalised projects. For a legacy pixel-space project
    it is the largest coordinate seen, so every offset and clamp scales with it.
    """

    def __init__(self, extent: float = 1.0) -> None:
        self.extent = max(float(extent or 1.0), 1.0)

    @classmethod
    def detect(cls, points: Iterable[Point]) -> "SheetSpace":
        largest = 0.0
        for x, y in points:
            largest = max(largest, abs(float(x or 0)), abs(float(y or 0)))
        # Anything that fits in [0, 1.5] is a normalised sheet; a stray value
        # slightly above 1 is noise, not a reason to switch to pixel units.
        return cls(1.0 if largest <= 1.5 else largest * 1.05)

    def clamp(self, v: float) -> float:
        return min(self.extent, max(0.0, v))

    @property
    def offset(self) -> float:
        return NEW_NODE_OFFSET * self.extent

    @property
    def clearance(self) -> float:
        return MIN_CLEARANCE * self.extent


def nearest_dist(p: Point, points: Iterable[Point]) -> float:
    best = math.inf
    for q in points:
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if d < best:
            best = d
    return best


_LEFT = re.compile(r"\bleft\b")
_RIGHT = re.compile(r"\bright\b")
_UP = re.compile(r"\b(above|top|over|upper)\b")
_DOWN = re.compile(r"\b(below|under|beneath|bottom|lower)\b")


def parse_direction(text: str | None) -> tuple[int, int] | None:
    """An explicit side from the engineer's wording, or None.

    Long descriptive messages are ignored, same as the desktop version, to
    avoid reading "upper limit" in a paragraph of requirements as a side.
    """
    if not text or len(text) > 120:
        return None
    t = text.lower()
    dx = -1 if _LEFT.search(t) else (1 if _RIGHT.search(t) else 0)
    dy = -1 if _UP.search(t) else (1 if _DOWN.search(t) else 0)
    return (dx, dy) if (dx or dy) else None


def pick_free_spot(anchor: Point, occupied: list[Point],
                   preferred: tuple[int, int] | None = None,
                   space: SheetSpace | None = None) -> Point:
    """A position beside `anchor` that is clear of `occupied`."""
    space = space or SheetSpace()
    off, clear = space.offset, space.clearance
    ax, ay = anchor

    if preferred:
        pdx, pdy = preferred
        perp = (-pdy, pdx)
        for j in (0, 1, -1, 2, -2):
            cand = (space.clamp(ax + pdx * off + perp[0] * j * off * 0.6),
                    space.clamp(ay + pdy * off + perp[1] * j * off * 0.6))
            if nearest_dist(cand, occupied) >= clear:
                return cand
        # The engineer asked for this side explicitly: honour it even if tight.
        return (space.clamp(ax + pdx * off), space.clamp(ay + pdy * off))

    fallback = (space.clamp(ax + off), ay)
    fallback_score = -math.inf
    for dx, dy in PLACEMENT_DIRECTIONS:
        cand = (space.clamp(ax + dx * off), space.clamp(ay + dy * off))
        score = nearest_dist(cand, occupied)
        if score >= clear:
            return cand
        if score > fallback_score:
            fallback_score, fallback = score, cand
    return fallback


def seed_spot(index: int, occupied: list[Point],
              space: SheetSpace | None = None) -> Point:
    """A starting position for a node with nothing to anchor to.

    The desktop version walks right along one row and, past a dozen nodes,
    clamps them all onto the sheet edge. This wraps onto further rows and
    skips occupied spots, so an empty or disjoint project stays legible.
    """
    space = space or SheetSpace()
    per_row = 10
    i = index
    while True:
        cand = (space.clamp((0.1 + (i % per_row) * 0.08) * space.extent),
                space.clamp((0.3 + (i // per_row) * 0.1) * space.extent))
        if nearest_dist(cand, occupied) >= space.clearance or i - index > 200:
            return cand
        i += 1


def place_new_nodes(existing: dict[str, Point], new_tags: list[str],
                    edges: list[tuple[str, str]],
                    preferred: tuple[int, int] | None = None,
                    anchor_tag: str | None = None) -> dict[str, Point]:
    """Positions for `new_tags`, anchored through `edges` to known nodes.

    `existing` maps tag -> position for nodes already on the sheet.
    `edges` are (from_tag, to_tag) pairs that may mix existing and new tags.
    `anchor_tag`, when given and known, seeds the first unanchored new node
    beside it instead of at a default spot.
    Returns only the new tags' positions.
    """
    space = SheetSpace.detect(existing.values())
    pos: dict[str, Point] = dict(existing)
    wanted = [t for t in new_tags if t not in existing]
    pending = set(wanted)
    seed_index = 0

    def occupied() -> list[Point]:
        return list(pos.values())

    for _ in range(max(20, len(wanted) * 4)):
        changed = False
        for a, b in edges:
            if a in pos and b in pending and b not in pos:
                pos[b] = pick_free_spot(pos[a], occupied(), preferred, space)
                changed = True
            elif b in pos and a in pending and a not in pos:
                pos[a] = pick_free_spot(pos[b], occupied(), preferred, space)
                changed = True
        if changed:
            continue
        unplaced = next((t for t in wanted if t not in pos), None)
        if unplaced is None:
            break
        if anchor_tag and anchor_tag in pos:
            pos[unplaced] = pick_free_spot(pos[anchor_tag], occupied(),
                                           preferred, space)
        else:
            pos[unplaced] = seed_spot(seed_index, occupied(), space)
            seed_index += 1

    for t in wanted:                       # anything still unplaced
        if t not in pos:
            pos[t] = seed_spot(seed_index, occupied(), space)
            seed_index += 1
    return {t: pos[t] for t in wanted}

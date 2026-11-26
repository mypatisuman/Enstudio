ROLE
================================================================================
You are tracing pipe and signal lines in ONE TILE cropped from a larger
P&ID page, {tile_w}x{tile_h} pixels. There is no upstream CV pass — you are
the only thing that finds lines in this tile. Nothing downstream will add a
run you miss, though a second verification pass will later check your work
against the full page.

Coordinates you output are PIXELS WITHIN THIS TILE ONLY (0,0 = tile
top-left) — never normalised, never relative to the full page.

{retry_note}

SYMBOLS ALREADY DETECTED IN THIS TILE (for reference — do not re-detect
these, use them as anchors for where pipes should start/end):
{symbol_list}

MISSION
================================================================================
Trace every distinct pipe or signal-line RUN visible in this tile as an
ORDERED sequence of points — NOT as a flat list of independent segments.
A run is one continuous line from where it starts (a symbol edge, a tile
boundary, or an open stub) to where it ends (another symbol edge, a tile
boundary, a junction, or an open stub), including every corner along the
way.

  • A run with no corners is just two points: start and end.
  • A run that turns 90° twice (goes right, then down, then right again) is
    three points: the two corners plus start and end — do NOT split it into
    three separate "segments" and report them independently; that is what
    makes you miss the fact they're one pipe.
  • A run straddling the tile edge (cut off by the crop): report the
    portion visible in this tile, ending at the tile boundary — a later
    merge step reconnects it with whatever the adjacent tile finds there.
  • When a run passes THROUGH a symbol (e.g. a pipe running through an
    inline valve rather than terminating at it), keep tracing past the
    symbol as one continuous run — do not break it into two runs at every
    symbol it touches. Only break the run where a symbol is genuinely the
    END of that pipe (e.g. it feeds into a vessel nozzle).
  • Where two runs cross with no junction dot / no shared endpoint, they
    are NOT connected — trace them as two separate runs that happen to
    overlap visually, never merge them into one path through the crossing.

WHAT TO TRACE
================================================================================
  • Process pipes (solid lines).
  • Signal/instrument lines (dashed, dotted, or otherwise non-solid).
  • Set "style": "solid" or "style": "dashed" per run based on what you
    actually see — do not assume; a line drawn with small gaps at regular
    intervals is dashed even if individual dashes are only a few pixels.

EXCLUSIONS — do not trace these as lines
================================================================================
  • Symbol outlines themselves (a valve's bowtie body, a vessel's cylinder
    wall, an instrument bubble's circle) — those are shapes, not pipe runs.
  • Leader/pointer lines from a symbol to its own text label (short,
    one end at a symbol, other end at plain text with no continuing pipe).
  • Dimension lines, border lines, title-block rules, hatching/fill
    patterns inside equipment.
  • Arrowheads themselves (the triangle/chevron shape) — but DO trace the
    line the arrowhead sits on, ending your run at the arrow tip.

GRID-SCAN DISCIPLINE (mandatory — do this before writing JSON)
================================================================================
Divide THIS TILE into a 3x3 grid and scan cell by cell, left-to-right,
top-to-bottom, same as a symbol search — thin lines near tile edges and
lines that only briefly cross a cell are the easiest to miss:
  cell 1 (top-left)     cell 2 (top-mid)     cell 3 (top-right)
  cell 4 (mid-left)     cell 5 (centre)      cell 6 (mid-right)
  cell 7 (bottom-left)  cell 8 (bottom-mid)  cell 9 (bottom-right)
For each cell, note what runs pass through or originate there (or
"nothing new") before moving to JSON.

CONFIDENCE CALIBRATION
================================================================================
  0.90–1.00  Every point on the run is unambiguous at native resolution.
  0.70–0.89  Path is clear but one segment's exact corner position is a
             close call (e.g. obscured by a crossing pipe or symbol).
  0.50–0.69  You can tell a run is there and its rough path but exact
             corner coordinates are uncertain.
  Below 0.50 — do not report the run at all; omission is correct here, a
             low-confidence guess about pipe routing is worse than a gap
             the verification pass can catch from full-page context.

================================================================================
OUTPUT — reasoning then JSON
================================================================================
STEP 1 — GRID SCAN (9 lines, one per cell, in order, never skipped):
  "Cell 1 (top-left): run entering from left edge at y=40, goes straight
   to symbol at (120,40)."
  "Cell 5 (centre): nothing new (continuation of cell-4 run)."

STEP 2 — JSON OUTPUT:
```json
{
  "reasoning": ["<the 9 grid-scan lines, in order>"],
  "runs": [
    {"points": [[0, 40], [120, 40]], "style": "solid", "confidence": 0.00},
    {"points": [[300, 10], [300, 90], [360, 90]], "style": "dashed", "confidence": 0.00}
  ]
}
```
If the tile has no lines at all, output an empty "runs" array.

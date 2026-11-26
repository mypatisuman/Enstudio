ROLE
================================================================================
You are reading process text from ONE TILE cropped from a larger P&ID page,
{tile_w}x{tile_h} pixels. This is the FALLBACK path — no symbols have been
detected yet, so you are finding and reading text with no anchor to work
from. Coordinates you output are PIXELS WITHIN THIS TILE ONLY (0,0 = tile
top-left) — never normalised, never relative to the full page.

MISSION
================================================================================
List every distinct piece of PROCESS text visible in this tile — instrument
tags, equipment names, line numbers, valve tags, pipe size/spec callouts,
header/system names — with a tight bounding box and your best reading.

  • Text at any rotation (vertical, angled along a pipe) is in scope — read
    it as printed; do not skip it for being harder to scan.
  • Multi-line labels that clearly belong together (same object, adjacent
    lines, consistent alignment) — merge into one entry, space-separated,
    reading order top-to-bottom.
  • A symbol straddling the tile edge: read whatever text is visible in
    THIS tile; a later merge step reconciles duplicates from the
    overlapping neighbour tile.

EXCLUSIONS — do not report these
================================================================================
  • TITLE BLOCK / DRAWING METADATA: revision numbers, drawn-by/checked-by/
    approved-by names, scale notation, drawing number, client/project/
    company name, sheet number, date. This content clusters in a bordered
    block, almost always bottom-right or along the bottom edge of the sheet
    — if this tile is from that region and the text matches this category,
    skip it.
  • Dimension lines, north-arrow labels, revision-cloud callouts, and other
    pure drafting annotations with no process meaning.
  • Legend/schedule entries in a fenced-off grid of symbol+description rows
    that is clearly a key, not part of the process flow.

DESTINATION VS. TAG TEXT
================================================================================
Text that says WHERE fluid goes/comes from (starts with "TO", "FROM",
"RETURN TO", names a sump/pit/drain/area) is still in scope — report it, but
set "kind": "destination_text" rather than "kind": "tag" so a downstream
step can treat it differently from a real instrument/equipment tag.

CONFIDENCE CALIBRATION
================================================================================
  0.90–1.00  Every character unambiguous at native resolution.
  0.70–0.89  Legible with one or two close-call characters.
  0.50–0.69  Mostly legible, genuine ambiguity on multiple characters.
  Below 0.50 — do not report the entry at all; omission is correct here,
             not a low-confidence guess.

================================================================================
OUTPUT — JSON only, no other text
================================================================================
```json
{
  "detections": [
    {"text": "PIC-101", "bbox": [x1, y1, x2, y2], "kind": "tag", "confidence": 0.00},
    {"text": "TO FLARE HEADER", "bbox": [x1, y1, x2, y2], "kind": "destination_text", "confidence": 0.00}
  ]
}
```
If the tile has no process text at all, output an empty "detections" array.

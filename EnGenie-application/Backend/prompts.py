
CV_VERIFY_PROMPT = """\
ROLE
================================================================================
You are a P&ID symbol verification specialist. A CV pipeline already produced
imperfect detections from this drawing:
  1. YOLO — symbols  (type + bounding box)
  2. OCR  — text     (string + bounding box)
Using these detections AND the image, produce a clean verified NODE list.

MISSION
================================================================================
  • Verify/correct each symbol's type, merge true double-fire detections, and
    recover any symbol the CV pipeline missed — drop nothing silently.
  • Label each symbol from OCR (validated against the image); fall back to the
    YOLO class name only. Never invent a tag.
  • DO NOT trace connections, DO NOT output edges, DO NOT create junction
    nodes — a separate specialist handles piping. Output is NODES ONLY.

PRIORITY ORDER (when two signals disagree, the higher one wins)
================================================================================
  1. What the image visibly shows.
  2. The YOLO detection (type, bbox, existence).
  3. The OCR text.
  4. The ISA-5.1 reference table below.
  5. General heuristics / examples in this prompt.

THE 100% CERTAINTY GOLDEN RULE
================================================================================
You are STRICTLY FORBIDDEN from deleting, dropping, merging, or updating ANY
detected symbol unless you are 100% undeniably certain it is incorrect. Even
1% doubt → keep the detection exactly as provided. Fidelity to the raw data
outranks "cleaning up" the diagram. This rule governs every check below.

PIPELINE
================================================================================
Complete each step for EVERY symbol before starting the next — do not
interleave steps or jump ahead. Finish the whole pipeline, then write JSON.
  STEP 1 — SYMBOL CHECK: confirm the type of every YOLO detection against the
           image (SYMBOL RULES). Do not continue until every detection is done.
  STEP 2 — LABEL CHECK: assign each symbol's tag from OCR or the image
           (LABEL RULES). Do not continue until every label is assigned.
  STEP 3 — MERGE CHECK: resolve any double-fire detections (MERGE RULES).
  STEP 4 — MISSING-SYMBOL RECOVERY: grid-scan the whole image for symbols the
           CV pipeline missed (MISSING-SYMBOL RULES).
  STEP 5 — EDGE CASES: apply the special-case rules (EDGE CASES A-D: legends,
           pipe-end annotations, header connectors, equipment labels).
  STEP 6 — FINAL VALIDATION: run every check in FINAL VALIDATION before
           writing JSON.

SYMBOL RULES
================================================================================
For every YOLO symbol, compare the detection against what you see in that
region of the image (around the detected position, not the exact point).
Your primary goal is to RETAIN accurate detections — never miss or silently
drop a symbol.

  • Correct detection → keep exactly as-is, do not alter it.
  • Wrong type → check CONFIDENCE GUARD below FIRST. If confidence >= 0.80 and
    no guard exception applies, keep YOLO's type — the guard wins. Otherwise
    correct it to what the image shows, per the GOLDEN RULE.
  • Region clearly empty and a false positive, per the GOLDEN RULE → do NOT
    drop it; keep it as a node with isolated_reason explaining the false
    detection.

  ADJACENT & INLINE SYMBOLS: clusters of touching/adjacent symbols (valves
  beside filters, small ball valves on vessels, series of circles) are usually
  separate physical objects. Keep every YOLO detection unless it is a
  double-fire (two boxes on the EXACT SAME object) per the GOLDEN RULE — never
  merge or drop distinct touching shapes, and never drop a symbol for being
  small or close to a larger one.

  CONFIDENCE GUARD: for confidence >= 0.80, apply this guard FIRST, before the
  GOLDEN RULE — never drop, flag false, or retype to a broader/generic
  category, even if you think you're 100% certain. Only if one of the two
  exceptions below applies is the guard lifted and the GOLDEN RULE allowed to
  act. Otherwise a type change is valid only when YOLO's shape call is
  completely wrong (not a more/less specific name for the same shape) — keep
  YOLO's type when in doubt. The two exceptions:
    (a) Plain text with NO enclosing shape at all (a bare label/tag/drain name
        floating on the sheet) → isolated_reason "text label, not a symbol",
        no edges, any confidence.
        THE RULE: text INSIDE a drawn shape is that symbol's TAG, never a text
        label. If anything is drawn around the text, it is a symbol — keep it
        and leave isolated_reason unset. Only text with nothing drawn around it
        is a label. A flagged node can never carry a pipe, so mis-flagging one
        symbol silently deletes every connection into it.
    (b) Invalid ISA type string (mutually-exclusive letters combined,
        meaningless sequence, or a category instead of a function) → correct
        the type field to the nearest valid ISA type matching both the shape
        and tag (see ISA-5.1 REFERENCE). Position, bbox, and existence stay
        protected either way.

  OVERLAPS: count distinct physical shapes visible → output that many nodes,
  never fewer. Merge ONLY a true double-fire (two boxes on ONE physical
  object). Centres differing in Y by >0.02 normalised units are always two
  objects, regardless of bounding-box overlap (valve beside filter = 2; two
  boxes on one circle = 1).

  CONSERVATION LAW (unbreakable): every YOLO detection MUST appear in the
  output — either as its own node or recorded in another node's
  "merged_from". Nothing disappears silently.

LABEL RULES
================================================================================
  • OCR text 100% certain correct → keep it as the tag.
  • Not certain, or no text detected → fall back to the YOLO class name only.
    Never invent a tag.

  RECOVER MISSING/PARTIAL TEXT: if OCR missed a tag or captured only part of a
  multi-line label, read the full tag directly from the image — only when you
  can clearly read every character. Combine multi-line labels into one
  space-separated string in drawing order. A single short word (e.g. "FC",
  "HV", "BV") as the only OCR for a valve/instrument is almost always a
  partial capture — check the image for a second line.

  YOLO-FALLBACK DETECTION: if a node's label is identical to its YOLO type
  string (differs only by underscores/capitalisation), OCR found nothing and
  the system fell back to the type name — always attempt to read the real
  label from the image before accepting that fallback.

  ONE COMPLETE TAG PER SYMBOL: text inside a symbol's box belongs to that
  symbol; text beside a symbol belongs to the nearest symbol whose box it
  touches. Each text item belongs to exactly ONE symbol — on ties, assign to
  whichever box directly contains/overlaps the text; if still tied, the OCR
  entry nearer the symbol centre, then whichever appears first in cv_summary.
  Combine all of a symbol's text into one complete tag.

  DESTINATION/DRAIN TEXT — never assign as a symbol label (except connector
  labels in EDGE CASES): text that describes WHERE fluid goes rather than
  WHAT the component is (starts with a routing word like "TO"/"FROM"/"RETURN
  TO", or names a system/header/sump/pit/drain/area instead of carrying an
  ISA tag structure) is never a symbol's tag, even if it's the only nearby
  OCR — leave that symbol unlabeled (YOLO type name) instead.

MERGE RULES
================================================================================
On a double-fire, the higher-confidence detection survives (equal confidence →
lower index survives); the absorbed detection's id goes in "merged_from".

MISSING-SYMBOL RULES
================================================================================
"Visually scan the whole image" is not enough on a large drawing — you WILL
miss things in the region you scan last. You MUST scan in explicit horizontal
bands and report on EVERY band, even if empty.

  1. Divide the image into 10 horizontal bands by normalised y:
       band 1: y 0.00–0.10   band 6:  y 0.50–0.60
       band 2: y 0.10–0.20   band 7:  y 0.60–0.70
       band 3: y 0.20–0.30   band 8:  y 0.70–0.80
       band 4: y 0.30–0.40   band 9:  y 0.80–0.90
       band 5: y 0.40–0.50   band 10: y 0.90–1.00
  2. For EACH band, in order 1→10, write one line even if nothing is found:
       "Band N (y=Y1–Y2): scanned left→right. <finding, or 'no missed symbols'>."
  3. Pay special attention to bands 9-10 (bottom of sheet) and band 1 (top,
     near title/border) — the most commonly under-scanned regions. Also
     re-check the far-right ~10% of every band (x > 0.85) for
     header/outlet/connector arrows, which cluster there.
  4. Do not skip a band. Do not summarise multiple bands in one line.

  PAIRED-CONNECTOR / CLOSED-LOOP CHECK: utility loops are drawn as paired
  supply/return headers (e.g. CWS/CWR, or two arrows into/out of the same
  equipment). Whenever you find ONE half of such a pair, explicitly check the
  same equipment's area for the OTHER half — even if it's a plain arrow with
  less visual weight, or sits below/behind other equipment. State in the band
  scan line whether the pair was found complete or is genuinely absent.
  "Found complete" means you located the second connector's SHAPE — it says
  nothing about its type. Read that second connector's own arrowhead
  separately before assigning Outlet/Inlet; do not assume it mirrors the
  first half just because the pair is now complete.

  Rules for adding a new node:
    • Only add when 100% certain a physical ISA shape (or header arrow per
      the CRITICAL DISTINCTION rule in EDGE CASES) exists in the image.
    • Assign the id continuing the series, in grid-scan order (band → left-
      to-right within the band).
    • Set x, y to the normalised centre you see (2 decimals); confidence 0.80.
    • Set type/category/label from what you can read. Header/outlet arrows
      get category "connector" and a type chosen from the arrow's direction:
      arrow points OUT of the drawing (flow leaves) → type "Outlet"; arrow
      points INTO the drawing (flow enters, e.g. a return/supply-in header)
      → type "Inlet". Use "Off_Page_Connector" instead of either when that
      type is already used elsewhere in this cv_summary.
      DETERMINE THIS FROM THE ARROWHEAD ALONE, every time, even for a header
      you've already seen the pair of (e.g. CWS/CWR, supply/return). Never
      infer Inlet vs Outlet from: the header's name, which side of the sheet
      it's on, expected process flow, or "this looks like the return line so
      it must be the opposite of the one I already added." A supply/return
      pair is not guaranteed to point opposite ways just because they're a
      pair — read each arrowhead on its own before deciding its type.
    • Any doubt → do NOT add.

  Do NOT add: text-only labels/annotations/drain labels/area tags/notes with
  no arrowhead and no header/system name; arrows that only show flow
  direction on a continuing (non-stub) pipe; Off_Page_Connectors/Outlets not
  at the edge of the drawn process area AND without a header/system name +
  arrowhead.

EDGE CASES
================================================================================

  A. NON-PROCESS REGIONS (legend / schedule / title block)
  --------------------------------------------------------------------------
  Symbols arranged in a regular grid/row with description blocks, fenced off
  from the main flow and not pipe-connected, are NOT process symbols — set
  isolated_reason, no edges. The confidence guard does NOT protect
  legend/schedule icons.

  B. PIPE-END DESTINATION ANNOTATIONS (must be isolated)
  --------------------------------------------------------------------------
  A detection is an annotation, not a process symbol, when ALL of the
  following hold in the image:
    (a) it's only TEXT (possibly in a plain rectangle/flag/arrow box) with no
        distinct ISA graphic shape (no filled circle, bowtie, diamond,
        pentagon, cylinder, or triangle enclosing/adjacent to the text);
    (b) it sits at the open terminus of a stub pipe with no continuing pipe
        beyond it;
    (c) it carries no instrument loop number, no measurement function letter
        (P, T, F, L, A…), and no ISA tag prefix structure.
  Meeting (a)+(b)+(c) → isolated_reason "pipe destination annotation, not a
  process symbol", any confidence; the guard does not protect annotations.
  A real valve on the same stub is a separate physical shape and stays its
  own node — only the text-box annotation beside it is isolated.

  C. HEADER/OUTLET CONNECTORS (destination text vs. header connector)
  --------------------------------------------------------------------------
  CRITICAL DISTINCTION: a line-end label is a process Outlet/Inlet/
  Off_Page_Connector node ONLY when it BOTH has an arrowhead (►, ◄, open
  triangle) AND names a system/header (e.g. "CWS HEADER►", "N2 HEADER
  1-1-120") — keep/add it regardless of page position, even without a
  continuing pipe. The header/system name is the deciding factor, not the
  arrowhead alone (arrows appear on plain destination stubs too). The
  arrowhead's direction decides Outlet (points out) vs Inlet (points in) — see
  MISSING-SYMBOL RULES. A drain/sump/pit label (e.g. "OVERFLOW DRAIN") is an
  annotation and stays isolated even with an arrowhead, since it carries no
  header/system name.

  CONNECTOR / OUTLET LABELS: for nodes typed "Outlet"/"Inlet"/"Off_Page_Connector" (or
  any connector variant), the nearest OCR text — even a header/system/area
  name — IS the correct label; always assign it. This overrides the
  destination/drain-text rule (LABEL RULES) for these node types only.

  D. EQUIPMENT LABEL BOXES
  --------------------------------------------------------------------------
  A rectangular text box above/beside a piece of equipment with no pipe
  connections of its own is an equipment label, not a process symbol. Set
  "equipment_ref" to the adjacent equipment node's id — this places the
  label on the canvas instead of as a separate connected node.

  E. SYMBOLS NESTED INSIDE A PACKAGE BOUNDARY
  --------------------------------------------------------------------------
  Any symbol (instrument bubble, small mechanical item, etc.) drawn physically
  INSIDE a "package" or "vendor_package" boundary box — not merely nearby, but
  visually contained within its border — MUST have "equipment_ref" set to that
  boundary box's node id, the same as an equipment label box. This is what
  places it nested inside the box on the canvas instead of as a separate
  sibling node pushed out to avoid overlapping it.

  Boundary boxes NEST. A vendor package commonly contains a smaller labelled
  equipment box, which in turn contains the instruments. When a symbol sits
  inside more than one boundary, set "equipment_ref" to the INNERMOST box that
  contains it — never the outer one. And a boundary box that is itself drawn
  inside a larger boundary MUST carry its own "equipment_ref" pointing at that
  larger box, exactly like any other contained symbol.

  Worked example — an AT bubble inside a "GCV-XXXX" box inside a vendor package:
      {"id":"n40","kind":"vendor_package","label":"VENDOR PACKAGE"}
      {"id":"n39","kind":"package","label":"GCV-XXXX","equipment_ref":"n40"}
      {"id":"n27","kind":"analyzer","label":"AT XXXX","equipment_ref":"n39"}
  Setting n27's ref to "n40" (the outer box) is WRONG — it flattens the
  hierarchy and leaves the GCV box floating unattached.

NODE IDS & REQUIRED FIELDS
================================================================================
Assign ids in cv_summary order: symbol [1] → "n1", [2] → "n2", … [N] → "nN".
A merged symbol keeps the surviving id and records the absorbed one in
"merged_from"; added symbols continue the series (n<last+1>, …) in grid-scan
order. Never create junction nodes — that's the connections specialist's job.
Every node MUST carry:
  • "type"     — the EXACT YOLO type string from the cv_summary, preserving
                 capitalisation/underscore format (e.g. "Control_Valve"). When
                 correcting a type, match that same format. If a symbol type is
                 completely missing from the cv_summary but you are 100% certain
                 by eye that its explicit physical shape exists in the image
                 (e.g., a clear Hand_Valve, Quick_Connect, or Thermocouple_Element
                 sitting on a pipe), you may use a standard YOLO type name. Do
                 NOT guess based on stray marks or text alone. If added, its
                 coordinates MUST be exactly on the pipe.
  • "kind"     — for Thermocouple_Element (output "thermocouple") and
                 Quick_Connect (output "quick_connect"); this ensures the
                 special physical shape renders correctly. ALSO required on
                 any boundary-box node per the ISA-5.1 SHAPE→KIND table below
                 ("vendor_package" / "package") — that table's rule is not
                 overridden by this one.
  • "category" — one of: equipment | instrument | mechanical | connector.
Without both, the canvas renders the node as a blank box.

ISA-5.1 REFERENCE
================================================================================
SHAPE → KIND: circle = instrument bubble; trayed/packed tall cylinder = column;
  coiled/jacketed tall cylinder = reactor;
  horizontal cylinder + tubes = heat_exchanger; trapezoid / impeller = pump;
  bow-tie + actuator = control_valve; circle-on-pipe = hand_valve; filled
  triangle = check_valve; triangle+hat or spring disc = relief_valve;
  arrow-in-flag = off_page_connector; solid vertical rectangle inline on pipe = Quick_Connect;
  probe/heavy dot on pipe (often labelled TC/TE) = Thermocouple_Element;
  large dashed boundary box enclosing items = Vendor_Package (MUST output "kind": "vendor_package");
  solid boundary box enclosing items = Equipment_Box (MUST output "kind": "package").
PLAIN PRESSURE VESSEL ORIENTATION — a dished-head cylinder with no trays/coil
  is a vessel, not a column/reactor. Its "kind" MUST record which way it's
  drawn, since the canvas renders vertical and horizontal vessels as visibly
  different symbols:
    • standing upright (taller than wide)  → "kind": "vessel_v"
    • lying on its side (wider than tall)  → "kind": "vessel_h"
  Then refine "kind" further by tag prefix or label, else fall back to the
  orientation above: KO- prefix or "knockout" in label → "knockout";
  D- prefix with "flash" in label → "flash_drum"; "accumulator" in label →
  "accumulator"; flat-bottomed tank on grade with no dished heads → "tank_atm";
  conical-bottom bin/silo → "hopper". Never output the bare word "vessel" —
  it loses the orientation the shape actually shows.
TAG PREFIX → KIND: PCV/FCV/TCV/LCV/HCV = control_valve; HV = hand_valve;
  XV/SV = solenoid_valve; PSV/PRV/BPR = relief_valve; CK/NRV = check_valve;
  PI/TI/LI/FI = indicator; PT/FT/LT/TT = transmitter; PIC/FIC/TIC/LIC = controller;
  PSL/PSH/TSL/TSH/FSL/FSH = switch; PAL/PAH/… = alarm; AE/TE/FE/PE/LE/ZE = element;
  MFM = meter (inline); B- = pump.

DETERMINISM (identical input MUST produce identical output)
================================================================================
  • Coordinates on kept YOLO nodes are copied character-for-character from the
    cv_summary — never re-rounded, never re-estimated. Only added nodes get
    new coordinates (2 decimals).
  • Uppercase tags exactly as printed; collapse multi-line labels with single
    spaces; no trailing spaces.
  • Omit empty/unknown optional fields entirely — never null, "", or [].

FINAL VALIDATION — run before writing output
================================================================================
  1. Conservation: every YOLO detection appears as its own node or in "merged_from".
  2. Grid scan complete: all 10 bands reported, in order, none skipped.
  3. Paired-connector check done for every supply/return-style header found.
  4. No merges of nodes whose centres differ in Y by more than 0.02.
  5. Type format matches cv_summary exactly; no invented type names.
  6. Coordinates on kept nodes are byte-identical to cv_summary.
  7. Labels: no invented suffix/prefix; duplicate labels across nodes are fine.
  8. equipment_ref set on every label box with no pipe connections.
  9. No empty fields (no null, "", or []).
  10. Output contains NODES ONLY — no "edges" key, no "junctions" key.
  11. Every node at a stub terminus with only text and no arrowhead has
      isolated_reason set.
  12. Every vessel/tank/major-equipment node has a meaningful label (equipment
      tag, fluid/service name, or nameplate text) — not the raw YOLO type
      name, unless the image genuinely shows no text on/near it.
  13. Every non-ISA-tag, non-equipment-tag label is checked: if it describes
      where fluid goes and has no arrowhead, clear it back to the YOLO type name.
  14. Node array is in ascending numeric id order; coordinates verified
      byte-identical to cv_summary.

================================================================================
CV DETECTIONS — verify these against the image; do not ignore any
================================================================================
{cv_summary}
================================================================================

OUTPUT — reasoning then JSON
================================================================================
STEP 1 — REASONING (work through each symbol before committing to JSON):
For each detection in cv_summary order, write one line:
  "<id> <type> (<x>,<y> conf=<c>): <shape> confirmed in image → keep, tag=<TAG> from OCR."
  "<id> <type> (<x>,<y> conf=<c>): <shape> confirmed → keep, tag=<TAG> read from image (OCR partial/missed)."
  "<id> <type> (<x>,<y> conf=<c>): text only at stub terminus, no ISA shape, no arrowhead → isolated."
  "<id> (<x>,<y> conf=<c>): double-fire on same physical object as <other-id> → merge into <other-id>."

STEP 2 — MANDATORY GRID SCAN (10 lines, one per band, in order — see above):
  "Band 1 (y=0.00–0.10): scanned left→right. no missed symbols."
  "Band 9 (y=0.80–0.90): scanned left→right. found arrow-terminated header
   'CWR HEADER' at (0.90,0.95) with no matching node in existing list → add as n<N>."
  ... (all 10 bands)

STEP 3 — VALIDATION: run all 14 checks above. Write "VALIDATION OK" or list
each fix made (e.g. "Fix check-12: nX label was YOLO type name, read <label>
from image.").

REASONING PLACEMENT (provider-dependent — both are valid):
  • If you can write free text before the JSON: write STEPs 1–3 as prose, then
    the JSON in a ```json fence, and OMIT the "reasoning" key from the JSON.
  • If your output is constrained to JSON only (structured output mode):
    write every STEP 1–3 line, in order, as strings in the top-level
    "reasoning" array — it must be the FIRST key you produce, before "nodes".
    The last reasoning string is the validation verdict.
Either way, the reasoning lines (including all 10 band-scan lines) are
MANDATORY — never skip them, never merge bands together.

STEP 4 — JSON OUTPUT:
```json
{
  "reasoning": ["<only in constrained/structured-output mode — omit otherwise>"],
  "drawing": {"number": "<drawing-number>", "title": "<drawing-title>"},
  "nodes": [
    {"id": "n1", "label": "<TAG>", "type": "<Yolo_Type>", "category": "<category>",
     "x": 0.00, "y": 0.00, "confidence": 0.00, "texts": ["<TAG>"]},
    {"id": "n2", "label": "<TAG>", "type": "<Yolo_Type>", "category": "<category>",
     "x": 0.00, "y": 0.00, "confidence": 0.00, "texts": ["<TAG>"], "equipment_ref": "<equipment-node-id>"},
    {"id": "n3", "label": "<TAG>", "type": "<Yolo_Type>", "category": "equipment",
     "x": 0.00, "y": 0.00, "confidence": 0.00}
  ]
}
```
Output NO "edges" key and NO "junctions" key under any circumstances.
"""


CV_CONNECTIONS_PROMPT = """\
ROLE
================================================================================
You are a P&ID pipe connection AUDITOR. A geometric algorithm has already
built a CANDIDATE connectivity graph directly from detected line segments —
pure coordinate math, no vision involved in building it. Your job is to check
that candidate graph against the actual drawing IMAGE and correct it: confirm
what's right, fix wrong directions/kinds, delete what's fabricated, and add
only what you are 100% certain is missing.

MISSION
================================================================================
  • For each PROPOSED EDGE: look at the image at that location. If a real,
    continuous pipe genuinely joins those two ends → KEEP it (set its flow
    direction + line kind). If it does NOT — the geometry matched two things
    that aren't really piped together (a nameplate leader line, two unrelated
    pipes that only crossed near each other, a dimension/reference line) →
    DELETE it.
  • For each CANDIDATE STUB (a detected line whose real endpoint the geometry
    could not confirm — usually because the detected segment fell short of
    its true target): look at the image. If it is 100% certain the pipe
    continues on to the suggested candidate symbol (or a different one you
    can clearly see it reaching) → ADD that edge. Otherwise leave it alone —
    do not invent a connection for an honestly unresolved stub.
  • For each UNMATCHED SYMBOL (geometry found NO detected line anywhere near
    it at all — a detection gap, not a judgment call): look at THIS symbol
    specifically in the image. If you can clearly see a real pipe leaving it
    and reaching a specific other symbol, 100% certain → ADD that edge. This
    is the one case where you are allowed to look beyond the candidate list,
    because geometry produced nothing at all to audit here — but the same
    100%-certain bar applies.
    Read the "nearest / distance" given for each one. A symbol sitting a few
    pixels from another (a tank beside its ball valve, a vessel beside its
    nozzle valve) is almost always JOINED by a nozzle too short for the line
    detector to resolve as its own segment — geometry reports nothing there
    because there is no line to report, not because the item is unpiped. Look
    at that specific pair in the image and ADD the edge when you can see they
    connect. Genuinely isolated items — spare/unpiped equipment, an instrument
    with no visible line, anything with no symbol close by — should still be
    left alone.
  • NOT EVERY REAL CONNECTION HAS AN EXISTING SYMBOL AS ITS TARGET. An
    instrument tap (PI, TI, FE, TE...) connects to a POINT on a main pipe, not to
    another symbol — the same is true for a stub or unmatched symbol whose
    line runs into the middle of an already-confirmed pipe rather than into a
    shape. When that's what the image shows, ADD is not limited to "connect
    to an existing id" — you may CREATE A NEW JUNCTION at the tap point
    (assign it a fresh id like "gj_new_1", set its x,y from the image) and
    then add the two/three edges that meet there (tap → junction, and the
    junction spliced into the pipe it taps onto). To splice a tap, you MUST
    delete the original continuous pipe edge and replace it with two segments
    meeting at the new junction.
    A JUNCTION IS ONLY FOR A POINT WHERE THREE OR MORE THINGS MEET. If a
    pipe simply runs from one symbol to another — a tank to its ball valve,
    a valve to the next valve — connect them DIRECTLY: one edge, symbol to
    symbol. Do NOT invent a junction between them. A bend or corner in a
    pipe is still that one edge, not a junction. A junction that ends up
    joining only two things is always wrong — emit the single direct edge
    instead.
  • INLINE SPLICING: If an unmatched inline component (valve, quick connect,
    reducer, etc.) sits directly ON a proposed continuous edge from A to B,
    you MUST splice it in: DELETE the original A->B edge and ADD two new
    edges: A-><inline_symbol> and <inline_symbol>->B.
  • You are primarily auditing the proposed graph, but the computer vision 
    pipeline can sometimes miss faint pipes entirely. If you clearly see a pipe 
    connecting two symbols that is completely missing from the proposed graph 
    (no proposed edge, no candidate stub), you MUST add it. Your job includes 
    finding these blind spots.
  • Output is EDGES and JUNCTIONS ONLY — the node list was finalised earlier;
    output NO "nodes" key.

PRIORITY ORDER (when two signals disagree, the higher one wins)
================================================================================
  1. What the image visibly shows (the drawn line itself).
  2. Whether a real pipe is continuous and unbroken between the two ends.
  3. The candidate graph's proposal — a starting hypothesis, not a fact.

THE AUDIT GOLDEN RULE (symmetric — governs keeping, deleting, AND adding)
================================================================================
  • KEEP a proposed edge unless you are 100% certain it does NOT correspond
    to a real, continuous, visible pipe. Even 1% doubt → KEEP it rather than
    delete it. The geometry that produced it came from a real detected line,
    so default to trusting it unless you can clearly see it's wrong (e.g. it
    is actually a nameplate leader, a dimension line, or two separate pipes
    that only cross with no dot).
  • ADD a new edge (or a new junction, for a tap onto an existing pipe) from
    a candidate stub or an unmatched symbol ONLY when 100% certain and you can 
    visually trace a continuous black line. Missing edges are preferred over invented ones.
  • Never invent an edge with no grounds at all in the candidate data — you
    are correcting and filling a specific, bounded list, not generating new
    hypotheses freely.

PIPELINE
================================================================================
  STEP 1 — Go through every PROPOSED EDGE, in order. For each, look at the
           image between its two endpoints and decide: KEEP (set direction +
           kind) or DELETE (state why — e.g. "nameplate leader, not a pipe").
  STEP 2 — Go through every CANDIDATE STUB, in order. For each, look at the
           image near its point and the symbol it's near. Decide: ADD (to the
           candidate symbol, a different symbol you can see it reaching, or a
           NEW junction if it taps onto a pipe — only if 100% certain and you 
           can visually trace the physical line, state the destination + direction) or LEAVE UNRESOLVED.
  STEP 3 — Go through every PROPOSED JUNCTION. Confirm it's a real dot/branch
           point in the image, not a crossover; if it isn't real, drop it and
           its degree-1 remnants.
  STEP 4 — Go through every UNMATCHED SYMBOL. Look at it specifically in the
           image. ADD an edge only if 100% certain and you visually trace a 
           continuous line that reaches a specific other symbol OR a specific 
           point on an already-confirmed pipe; otherwise leave it unconnected.
  STEP 5 — MISSING EDGES & OPEN PORTS: Scan the image between related process 
           equipment. CRITICAL: If an inline component (like a valve) has only 
           ONE pipe connected to it, you have 100% engineering certainty that a 
           second pipe exists. Visually follow the open port to find the missing pipe and ADD it.
  STEP 6 — Run FINAL VALIDATION, then write JSON.

LINE RULES (use these when judging a proposed edge or stub)
================================================================================
  • The line must run as a continuous, visible pipe with no unexplained gap.
  • THE OTHER END IS WHATEVER THE LINE ACTUALLY TOUCHES — never the nearest
    symbol. Proximity is NOT a connection. A pipe must physically touch a symbol.
  • A pipe must NEVER cross completely through the body of one component to reach another.
  • SET FLOW DIRECTION: look for an arrowhead — it always points in the direction of flow, toward the "to" (downstream) end.
    No arrow -> the left or top symbol is "from" (assuming standard gravity or left-to-right flow).
    Drains/vents are incoming only (sinks). Pumps take flow in (suction/inlet = "to" end of upstream pipe) and discharge it out (outlet = "from" end of downstream pipe). Tanks have both inlets (flow enters, tank is "to") and outlets (flow leaves, tank is "from"). A header/off-page
    connector follows its OWN arrow: arrow into the drawing = source; arrow
    out = sink.
  • SET THE LINE KIND from how the line looks, NOT from symbol type: solid
    continuous → "process"; dashed/dotted or thin line between two
    instrument bubbles → "signal"; double cross-slash marks → "pneumatic".

JUNCTION RULES
================================================================================
The clue is the little node/dot in the image: a filled DOT where lines meet =
a real junction (they connect); NO dot / one line hopping over another =
crossover (they do NOT connect — the candidate graph never invents these on
its own, but always confirm a proposed junction really is a dot, not a
crossover the geometry happened to cluster together).
  • 90-DEGREE BEND: 2 edges, no branch — a corner, not a T.
  • T-JUNCTION: 3 pipes meet, a branch leaves the run.
  • CROSS / 4-WAY: 4 pipes meet at one point.
Every edge must be straight: its two ends share an X (vertical) or a Y
(horizontal) — never a diagonal. Junctions live ONLY in the "junctions" array,
never in the node list.

PATTERN RULES (use these to judge whether a proposal makes engineering sense)
================================================================================
  INSTRUMENT TAP: a bubble (PI, TI, PT, FE...) dropping a short stub onto a
  main pipe is a tap, not a flow-splitting branch. 
  CRITICAL RULE: A main process pipe NEVER routes *through* an instrument bubble. 
  If the candidate graph proposes a pipe going into a PI and then out of the PI 
  to a valve, it is WRONG. You MUST delete the pipe leaving the bubble and 
  connect the main pipe directly to the valve instead. The bubble is just a side branch.

  TWO TRAINS MERGING: a standby/spare branch should join the MAIN PIPE at one
  T-junction upstream of a shared component (filter/header), not arrive at
  the component as a second, separate edge. If the proposal has two edges
  both landing directly on one component from two different upstream
  sources, check the image for a diamond/double-fire pattern — that usually
  means one physical pipe got proposed as two.

  INDEPENDENT TRAINS: each train runs to its OWN header/end; a proposed edge
  crossing from one train into an unrelated train's equipment is suspicious —
  verify it carefully before keeping it.

  HEADERS / CONNECTORS: An Inlet or Outlet arrow (e.g., CWS HEADER, TO FLARE) 
  almost always connects to EXACTLY ONE pipe at its tip or flat back. If the 
  candidate graph proposes multiple edges connecting to a single header arrow 
  (e.g., connecting it to two different valves), it is almost certainly a 
  hallucination. Identify the true pipe and DELETE the fake extra edges.

EDGE CASES
================================================================================
  NODES THAT GET NO EDGE: a label/legend/false detection with no pipe
  (isolated_reason or equipment_ref set) gets no edge — DELETE any proposed
  edge touching such a node; it is not connected to anything.

  NESTED-IN-PACKAGE INSTRUMENTS: an instrument bubble drawn physically INSIDE
  a "package"/"vendor_package" boundary box (e.g. an analyzer mounted inside a
  vendor skid) is a containment relationship, not a piped connection. If the
  candidate graph proposes an edge between such an instrument and its
  enclosing package/equipment box, and you cannot see an actual pipe line
  (as opposed to the box's own border, or the two shapes merely touching/
  overlapping) drawn between them → DELETE it. Only keep the edge if a real
  pipe distinct from the boundary line is visibly drawn connecting them.

FINAL VALIDATION — run before writing output
================================================================================
  a) Every KEPT edge corresponds to a continuous visible pipe you can point to.
  b) Every edge is straight (shared X or shared Y) — add the missing bend
     joint if not.
  c) DIAMOND / DOUBLE-COUNT CHECK: if two kept edges join the same pair of
     symbols, look at the image. Delete one ONLY when it is the SAME single
     physical pipe counted twice (one drawn line the geometry split into two
     proposals — the classic diamond artifact). If the image genuinely shows
     TWO distinct drawn pipes between those symbols (parallel/redundant runs,
     e.g. two trains to a shared header), KEEP BOTH — they are real.
  d) No edge has from == to. Duplicate from+to pairs are allowed ONLY when (c)
     confirmed two physically distinct parallel pipes; otherwise collapse to one.
  e) Every junction you keep connects at least 2 edges; drop degree-<2 remnants.
  f) Every ADDED edge is backed by 90% certainty from the image — if you
     can't point to the exact drawn line, remove the addition.
  g) equipment_ref / isolated_reason nodes carry no edges.
  h) ORPHAN RE-CHECK: for every candidate stub and unmatched symbol you left
     unresolved, confirm you actually looked at the image for it (per STEP 2
     and STEP 4) rather than skipping it — do not silently leave something
     connectable unconnected just because it's late in a long list.
  i) GAP CHECK (applies to anything you ADDED): a new edge or junction must
     follow ONE continuous visible line — never bridge a gap between two
     separate, unconnected line runs just because they're roughly aligned or
     nearby. This applies with full force to new taps/junctions you create,
     not just to kept proposals.
  j) LOOP CHECK (applies to anything you ADDED): one physical pipe = one
     edge/chain. Do not let a new junction or edge create a closed loop you
     cannot actually see as a real pipe circuit in the image.
  k) COMPLETENESS REPORT: every process vessel, pump, exchanger, column and 
     filter normally has at least one inlet AND one outlet pipe. Check if any 
     are missing. If you find a gap, scan the image closely to find the missing 
     pipe and ADD it. If you truly cannot find it, list the equipment as a 
     suspected MISSED connection.
  Fix any failures before output.

================================================================================
SYMBOLS (verified node list — reference only, do not re-verify)
================================================================================
{cv_summary}
================================================================================
PROPOSED CONNECTIVITY GRAPH (built by geometry — audit this, don't re-trace)
================================================================================
{proposed_graph}
================================================================================

OUTPUT — reasoning then JSON
================================================================================
STEP 1 — for each proposed edge, one line:
  "<idx> <from>-><to>: pipe confirmed in image -> KEEP, direction=<from/to>, kind=<k>."
  "<idx> <from>-><to>: NOT a real pipe (<reason>) -> DELETE."
STEP 2 — for each candidate stub, one line:
  "<idx> stub near <candidate>: image confirms pipe reaches it -> ADD edge <from>-><candidate>."
  "<idx> stub: taps onto the pipe between <A> and <B> at (x,y) -> ADD junction gj_new_N at (x,y),
   edges <from>->gj_new_N, <A>->gj_new_N, gj_new_N-><B>."
  "<idx> stub: no confirmation in image -> leave unresolved."
STEP 3 — for each proposed junction, one line confirming or dropping it.
STEP 4 — for each unmatched symbol, one line:
  "<id>: image shows a pipe reaching <other-id> -> ADD edge <id>-><other-id>."
  "<id>: taps onto the pipe between <A> and <B> at (x,y) -> DELETE edge <A>-><B>, ADD junction gj_new_N at (x,y), edges <id>->gj_new_N, <A>->gj_new_N, gj_new_N-><B>."
  "<id>: sits inline on the pipe between <A> and <B> -> DELETE edge <A>-><B>, ADD edges <A>-><id>, <id>-><B>."
  "<id>: no visible connection -> leave unconnected."
STEP 5 — for each completely new edge you discovered:
  "Discovered missing pipe between <A> and <B> -> ADD edge <A>-><B>."
STEP 6 — run FINAL VALIDATION checks a–k; write the result of each. For (k),
  list every under-connected process equipment as "GAP: <id> has <n> edge(s),
  expected inlet+outlet" so missed connections are visible even when unfixable.
STEP 7 — output the final connections in a ```json fence:
```json
{
  "junctions": [
    {"id": "tj_1", "x": 0.00, "y": 0.00}
  ],
  "edges": [
    {"from": "<node-id>", "to": "<node-id>", "kind": "process"}
  ]
}
```
Edge "kind" is one of: "process", "signal", "pneumatic".
Output NO "nodes" key - nodes were finalised by the previous stage.
"""

# ---------------------------------------------------------------------------
# JSON Schemas — split per stage, aligned with the prompts.
# ---------------------------------------------------------------------------

_NODE_SCHEMA = {
    'type': 'object',
    'properties': {
        'id':                   {'type': 'string'},
        'label':                {'type': 'string'},
        'type':                 {'type': 'string'},
        # Phase 1 schema-drift fix. extraction_cli/commands.py has always read
        # node['kind'], ['drawing'], ['area'] and ['description'] -- they feed
        # _KIND_TO_CATEGORY, the multi-drawing grouping and the equipment
        # table. None were declared here, so a provider that ENFORCES the
        # schema (Gemini / OpenAI structured output) stripped them and every
        # consumer read '' forever.
        'kind':                 {'type': 'string'},
        'drawing':              {'type': 'string'},
        'area':                 {'type': 'string'},
        'description':          {'type': 'string'},
        'category':             {'type': 'string', 'enum': ['equipment', 'instrument', 'mechanical', 'connector']},
        'x':                    {'type': 'number'},
        'y':                    {'type': 'number'},
        'confidence':           {'type': 'number'},
        'merged_from':          {'type': 'array', 'items': {'type': 'string'}},
        'isolated_reason':      {'type': 'string'},
        'equipment_ref':        {'type': 'string'},
        'range_lo':             {'type': 'number'},
        'range_hi':             {'type': 'number'},
        'units':                {'type': 'string'},
        'alarm_lo':             {'type': 'number'},
        'alarm_hi':             {'type': 'number'},
        'alarm_lolo':           {'type': 'number'},
        'alarm_hihi':           {'type': 'number'},
        'fail_position':        {'type': 'string', 'enum': ['open', 'closed', 'last']},
        'sil_level':            {'type': 'integer'},
        'loop_number':          {'type': 'string'},
    },
    'required': ['id', 'type', 'category', 'x', 'y', 'confidence'],
}

_EDGE_SCHEMA = {
    'type': 'object',
    'properties': {
        'from':       {'type': 'string'},
        'to':         {'type': 'string'},
        'kind':       {'type': 'string', 'enum': ['process', 'signal', 'pneumatic']},
        'segments':   {'type': 'array', 'items': {'type': 'string'}},
        'line_id':    {'type': 'string'},
        'line_size':  {'type': 'string'},
        'line_class': {'type': 'string'},
        'fluid':      {'type': 'string'},
        # Phase 1 schema-drift fix: both are read by _derive_studio_tables when
        # it builds the connections table; neither was declared. ('notes' went
        # the other way -- declared here, read by nothing.)
        'insulation': {'type': 'string'},
        'to_drawing': {'type': 'string'},
    },
    'required': ['from', 'to', 'kind'],
}

_JUNCTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'id': {'type': 'string'},
        'x':  {'type': 'number'},
        'y':  {'type': 'number'},
        'downstream_of': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['id', 'x', 'y'],
}

CV_VERIFY_OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'reasoning': {'type': 'array', 'items': {'type': 'string'}},
        'drawing': {
            'type': 'object',
            'properties': {
                'number': {'type': 'string'},
                'title':  {'type': 'string'},
            },
        },
        'nodes': {'type': 'array', 'items': _NODE_SCHEMA},
    },
    'required': ['nodes'],
    'propertyOrdering': ['reasoning', 'drawing', 'nodes'],
}

CV_CONNECTIONS_OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'reasoning': {'type': 'array', 'items': {'type': 'string'}},
        'junctions': {'type': 'array', 'items': _JUNCTION_SCHEMA},
        'edges':     {'type': 'array', 'items': _EDGE_SCHEMA},
    },
    'required': ['junctions', 'edges'],
    'propertyOrdering': ['reasoning', 'junctions', 'edges'],
}

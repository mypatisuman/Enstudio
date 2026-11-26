# PlantSketch Canvas & SVG Rendering Skill

## 1. Purpose

Canvas rendering skill for the PlantSketch editor and SVG export. Governs
symbol appearance, layer visibility, colour coding, spacing, and layout
order — the visual contract between the data model and what an engineer
sees on screen or in an export.

This skill is the **single source of truth for rendering decisions**.
Layout *positions* (X/Y coordinates, area ordering, backbone math) are
defined in `pid-development-rules.md` Part 5. Layer membership and
classification are defined in `pid-digitization-framework.md` Sections 4
and 7. This file ties those together with concrete, ISA-5.1-aligned
rendering rules.

Cross-references:
- `pid-development-rules.md` — Part 4 (rendering engine), Part 4.4
  (colour coding), Part 4.5 (symbol sizing), Part 5 (layout YAML).
- `pid-digitization-framework.md` — Section 4 (layer classification),
  Section 7 (node sizing).
- `pid-framework.md` — view presets and unconnected rules.

## 2. Layer Visibility Model

Every node carries a `pid_layer` (1–4) assigned at classification time.
View presets show or hide layers as a unit; the engineer can toggle
individual items via the "Show Unconnected" control.

| View preset | Layer 1 (equipment) | Layer 2 (instruments) | Layer 3 (mechanical) | Layer 4 (safety) |
|---|---|---|---|---|
| Process Only       | shown | hidden | hidden | hidden |
| Process + Control  | shown | shown  | hidden | hidden |
| Full P&ID          | shown | shown  | shown  | shown  |
| Safety Review      | shown | hidden | hidden | shown  |

Edges follow their primary layer:
- Process pipes (`stream`): always shown.
- Signal lines (`signal`): tied to Layer 2 visibility.
- Utility lines: tied to Layer 1 / Layer 3 of the touching utility node.
- Safety lines: tied to Layer 4.

**Defaults**:
- Layer 3 (hand valves, check valves, isolation, mechanical-only items)
  is **hidden by default**. These items remain in the data model and the
  YMPL/DXF exports, but clutter the canvas.
- Layer 4 (PSV/PRV/relief, ESD-driven solenoids in safety mode) is
  **hidden by default in operational views**, **shown in Safety Review**.

**Show Unconnected toggle**: when on, hidden items are revealed at 50%
opacity with a dashed orange border, so the engineer can spot orphans
and decide whether to connect or delete them. Toggle is independent of
the view preset.

## 3. Symbol Sizes (pixels at 300 DPI)

All values mirror Part 4.5 / Part 5 of `pid-development-rules.md`. The
canvas renders at logical pixels (1:1 with these values); SVG export
uses the same logical units.

| Kind | Width | Height | Shape | mask_padding | Notes |
|---|---|---|---|---|---|
| Vessel / drum / tank | 80 | 60 | rectangle | 12 | Slightly rounded `rx=3` |
| Heat exchanger       | 100 | 40 | rectangle | 10 | Elongated horizontal |
| Pump                 | 50 | 50 | circle    | 8  | Diameter = w |
| Compressor           | 60 | 60 | circle    | 10 | Diameter = w |
| Reactor              | 80 | 70 | rectangle | 15 | Larger pad — accommodates jacket |
| Filter               | 50 | 50 | rectangle | 8  | |
| Column / tower       | 50 | 120 | rectangle | 12 | Tall vertical |
| Control valve        | 40 | 30 | diamond   | 8  | Bowtie rendering |
| Instrument bubble    | 30 | 30 | circle    | 6  | ISA-5.1 bubble |
| Indicator (small)    | 20 | 20 | circle    | 5  | Local-only readout |

`mask_padding` is the pixel inflation used when computing a node's
bounding box for control-valve line-detection. It is *not* a visual
margin — it is the catchment area for "is this pipe touching this
node?" checks. See `engine.derive_bbox()`.

## 4. Color Standards (ISA-5.1 aligned)

All values mirror Part 4.4 of `pid-development-rules.md`.

### Edge styles

| Kind | Stroke | Width | Dash | Notes |
|---|---|---|---|---|
| Process pipe (`stream`) | `#475569` (dark grey) | 2.0px | solid     | Default backbone |
| Signal line (`signal`)  | `#1565C0` (blue)      | 1.5px | `6,3`     | Dashed pneumatic/electronic |
| Utility pipe            | `#0d9488` (teal)      | 1.5px | solid     | Glycol, hot oil, instrument air |
| Safety / relief         | `#dc2626` (red)       | 1.5px | solid     | PSV discharge, ESD lines |
| Recycle                 | `#7c3aed` (purple)    | 2.5px | solid     | Thicker — emphasises loop |

### Node fills

| Layer / kind | Fill | Border |
|---|---|---|
| Equipment (Layer 1)         | `#F1F5F9` (light grey)    | `#475569` 1.5px |
| Instrument bubble (Layer 2) | `#E3F2FD` (light blue)    | `#1565C0` 1.5px |
| Control valve (Layer 1)     | `#FFF3E0` (light orange)  | `#475569` 1.5px |
| Safety device (Layer 4)     | `#FDE2E2` (light red)     | `#dc2626` 1.5px |
| Mechanical valve (Layer 3)  | `#FFF3E0` (light orange)  | `#475569` 1.5px (50% opacity when hidden-but-shown) |

Tag text on all nodes: `#0f172a` (near-black), monospace, 10–11px.

## 5. X Ordering Rules

X position governs left-to-right process flow sequence. Always set X
*before* Y to keep the algorithm deterministic.

1. **Stream-graph positioned items** (equipment + control valves with a
   `sgPositions[id]` slot): use the stream-graph X. This encodes the
   reconstructed process flow order.
2. **Fallback items** (no stream slot but classified to an area): append
   **after** all stream-graph items in the same area, never before.
   Spacing: `X_STEP` (250px) from the rightmost stream-graph X in that
   area.
3. **Layer 3 / Layer 4 items**: assigned a position so they can be drawn
   when visible, but excluded from the backbone X sequence. Mechanical
   valves attach to the X of their nearest pipe; safety devices attach
   to the X of their parent equipment.
4. **Unconnected equipment**: placed at the end of its area group with a
   dashed orange border. If no area is known, dropped into a
   `_unassigned` band at the far right.

Within an area, ties are broken by tag-number order (e.g. `V-101`
before `V-102`).

## 6. Y Band Assignments

Y is layered by function. The backbone is the reference line; all other
bands are offsets from it.

| Band | Y (default) | Contents |
|---|---|---|
| Safety band            | 280  | PSV, PRV, relief, ESD-actuated valves (above backbone) |
| **Backbone**           | **400** | Process equipment + inline control valves |
| Indicator spoke        | +80  | Local indicators (PI, TI, LI) |
| Transmitter spoke      | +120 | FT, PT, TT, LT — primary measurement |
| Controller spoke       | +200 | FIC, PIC, TIC — below transmitter |
| Element inline         | 400  | Orifice plates, RTDs — same Y as the pipe they sit on |
| Utility band           | 1000 | Utility headers, glycol/hot-oil/IA equipment |

Spokes are vertical drops *below* the backbone for measurement chains
and *above* the backbone for safety devices. Multi-instrument groups on
the same parent spread horizontally with `multiple_spread = 50px`,
centred under the parent's X.

The backbone Y itself comes from `layoutRules.backbone.y` — keep this
file in sync with Part 5 if the default changes.

## 7. Edge Rendering Rules

Match the edge `kind` to the edge style table in §4. Style is a pure
function of kind — never override based on endpoints.

| Edge kind | Visual style |
|---|---|
| `stream`         | Process pipe |
| `signal`         | Signal line (dashed blue) |
| `utility`        | Utility (teal solid) |
| `safety`         | Safety/relief (red solid) |
| `recycle`        | Recycle (purple, thicker) |
| `bypass`         | Process pipe with `bypass` label |
| `inter_drawing`  | Purple dashed, combined view only — excluded from per-drawing exports |

**OCR artefact reclassification**: an extracted edge with `kind=stream`
but a `label` containing the word `signal` (case-insensitive) is
reclassified as `signal` *before* rendering. This catches a common
extractor failure mode where signal lines get parsed as pipes because
the dash pattern was missed in the source PDF.

```js
if (edge.kind === 'stream' && /signal/i.test(edge.label || '')) {
    edge.kind = 'signal';
}
```

The mutation lives in the rendering layer only; the underlying espx
node is left alone so the engineer can see and correct the original
extraction in the review pane.

## 8. SVG Export Defaults

| Export mode | Layers included | Notes |
|---|---|---|
| **Default**  | Layer 1 + Layer 2 | "Process + Control" — what an operator wants |
| **Full**     | Layer 1 + 2 + 3 + 4 | Complete P&ID with all mechanical and safety detail |
| **Safety**   | Layer 1 + 4         | Audit / safety review output |

Specifics:
- Layer 3 mechanical valves (HV, CK, NRV, isolation) are **excluded
  from the default export**. They appear only in the Full export.
- PSV / PRV / relief valves and ESD-driven solenoids (Layer 4) are
  **included in the default export** because they are safety-critical
  even on a "what runs in production" diagram.
- `inter_drawing` edges are excluded from every per-drawing export and
  appear only in the combined-view export.
- Crossing nodes (extraction-time geometry markers used to disambiguate
  pipe overlaps) are **excluded from every export**. They are rendering
  hints only.

The export honours the editor's layer-visibility state when the user
clicks "Export current view" but uses the defaults above when the user
clicks "Export plant" / "Export drawing zip".

## 9. Industrial Aesthetic Standards

The visual language is intentionally close to a clean engineering
drawing — restrained, monochrome-leaning, no chrome.

- **Editor canvas background**: `#0f172a` (slate-900) — dark grid, easy
  on the eyes for long sessions.
- **SVG export background**: `#FAFAFA` — neutral light, prints cleanly,
  matches the convention used by AutoCAD light-mode exports.
- **Tag font**: monospace (`'JetBrains Mono'`, `'Consolas'`, fallback
  `monospace`). Engineering tradition; also makes ISA-tag column
  alignment readable.
- **Node borders**: 1.5px stroke, slightly rounded corners (`rx=3` on
  rectangles). No drop shadows, no gradients — flat industrial look.
- **Area band labels**: small (8px), uppercase, muted colour
  (`#64748b`), placed at the top-left of each area band. Subtle so they
  don't compete with tag text.
- **Connection arrows**: filled triangles, 8px on the long axis,
  stroke-coloured to match the edge. Rendered at the destination end
  only; sources are unmarked.
- **Spacing**: 250px between major equipment along the backbone, 400px
  between unit-operation groups, 50px between sibling instruments on a
  shared spoke. These values are mirrored from
  `pid-development-rules.md` Part 5 and must change there first.

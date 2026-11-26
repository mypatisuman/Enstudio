# RULES.md — EngineeringStudio Architecture Rules
# These rules are non-negotiable. Do not violate them.

---

## Data Architecture

### Three node categories — never mix

| Category | Examples | Goes to |
|---|---|---|
| `INSTRUMENT_KINDS` | FT, TIC, PT, LT, AT, AIT, JS, JY, NA | VIDS instruments + enableSim |
| `PROCESS_KINDS` | Vessels, HX, reactors, pumps, columns | VIDS equipment + enableSim |
| `MECHANICAL_KINDS` | HV, CK, PSV, BPR, NRV | Topology edges only — NOT in VIDS or enableSim |

### Seven instrument types — only these strings allowed in VIDS
`transmitter` `controller` `indicator` `recorder` `switch` `analyzer` `element`

### Instrument schema fields
| Field | Type | Notes |
|---|---|---|
| tag | string | required |
| type | string | one of the 7 above |
| equipment_ref | string | primary process tag this instrument measures |
| range_lo / range_hi | float | engineering range |
| units | string | engineering units string |
| alarm_hi / alarm_hihi / alarm_lo / alarm_lolo | float | null unless on drawing |
| fail_position | open \| closed \| last | valve fail position |
| loop_number | string | controller tag for the loop this belongs to (e.g. FIC-101) |
| drawing | string | drawing number where tag appears |
| sil_level | 1 \| 2 \| 3 \| null | SIL rating — safety instruments only |
| confidence | float | 0.0–1.0 |

### Schema separation
- `VIDS` = operator view (engineering units, alarm limits, screen assignments)
- `YMPL` = simulation model (dimensionless, topology refs, Perry defaults injected by enableSim)
- Never write Perry physics into VIDS
- Never write enable.matrix in EngineeringStudio

### Cache rules
- Cache key = SHA256[:16] of file bytes
- pass0 = full combined result
- pass1 = topology only
- bN_pass2 = instrument batch N
- NEVER cache if nodes == 0
- Delete pass0 + pass1 to force re-extraction; pass2 batches persist

---

## Connection Types (ISA-5.1 / ISO 10628-2)

| Type | Line style | SVG stroke | Use for |
|---|---|---|---|
| `process` | Solid heavy | `#888` 2px | Main pipe, physical connection |
| `signal` | Dashed fine | `#4a6aaa` 1px dash 5,3 | DCS/instrument signal |
| `pneumatic` | Dot-dash | `#a06020` 1.5px dash 8,2,2,2 | Pneumatic tubing |
| `electrical` | Dashed medium | `#d0a000` 1.5px dash 6,3 | Electrical conduit |
| `hydraulic` | Double dashed | `#2080a0` 2px dash 4,2 | Hydraulic line |
| `capillary` | Fine dotted | `#808080` 1px dot 2,3 | Capillary tube |
| `recycle` | Solid blue | `#4a8fd4` 2px dash 8,3 | Recycle stream |
| `bypass` | Orange dashed | `#d06020` 1.5px dash 8,4 | Bypass line |

### Connection data fields (pipe-level attributes)
| Field | Type | Notes |
|---|---|---|
| id | string | ISA line designation e.g. `4"-N2-1001-A1B` |
| from_tag | string | upstream equipment or instrument tag |
| to_tag | string | downstream equipment or instrument tag |
| from_nozzle | string | nozzle label on from_tag (inlet, outlet, drain, vent, N1…) |
| to_nozzle | string | nozzle label on to_tag |
| type | stream \| signal \| recycle \| bypass \| pneumatic \| electrical | connection kind |
| fluid | string | process fluid description (natural gas, crude, cooling water…) |
| line_size | string | nominal pipe size string (4", 6", DN100) |
| line_class | string | piping class (150#, ANSI 300, etc.) |
| insulation | string | insulation type (H=heat, C=cold, P=personnel, null=none) |
| to_drawing | string | for off-page connectors — destination drawing number |

---

## Loops Schema

Loops are first-class objects in `espx.studio.loops`, keyed by **controller tag** (feedback/cascade) or **initiator tag** (safety/SIS).

```yaml
loops:
  FIC-101:
    type: feedback          # feedback | safety | ratio | cascade | feedforward
    measurement: FT-101
    controller: FIC-101
    final_element: FCV-101
    drawing: 157-2-110
    setpoint: 2500
    setpoint_units: kg/h
    sil_level: null
  PAHH-301:
    type: safety
    measurement: PT-301
    controller: null        # null = no DCS controller, SIS only
    final_element: XV-301
    drawing: 157-2-130
    sil_level: 2
```

Rules:
- Loops exported to VIDS (for DCS configuration), NOT to YMPL (simulation doesn't use loop structure)
- `sil_level` non-null means the loop appears in the SIS schedule
- `controller: null` is valid for safety loops with no DCS counterpart
- Inferred post-extraction from signal edges when not explicit in drawing

---

## Off-Page Connectors

Node kind: `off_page_connector`
- Represents a pipe run that continues to/from another drawing
- NOT in `INSTRUMENT_KINDS`, `PROCESS_KINDS`, or `MECHANICAL_KINDS`
- Stored in `espx.nodes[]` only — not in instruments or equipment
- Edge to/from an off_page_connector carries `to_drawing` attribute

```yaml
nodes:
  - id: n42
    label: "→ 157-2-140"
    kind: off_page_connector
    drawing: 157-2-130        # the drawing this connector appears on
edges:
  - from: n38
    to: n42
    kind: stream
    label: "6\"-PG-2001-A1B"
    to_drawing: "157-2-140"
```

---

## SVG Canvas Rules

### Coordinate system
- Canvas units: pixels, origin top-left
- Normalized positions from Claude: 0.0–1.0 mapped to canvas area
- Default canvas: 1400×900px per page
- Title block excluded from position area (bottom 15% reserved)

### Symbol rendering priority
1. Custom symbol from `symbols/<kind>.svg` (if file exists) — use `<use>` reference
2. Built-in ISA-5.1 geometric symbol from `svg_pid.py`
3. Fallback rectangle/circle

### Node sizing
- Process equipment: 56×36px bounding box minimum
- Instrument bubbles: 36px diameter circle
- Relief devices: 24px triangle

### Connection routing
- Orthogonal only (horizontal → vertical → horizontal)
- No diagonal lines
- Minimum bend radius: 0 (hard corners)
- Arrowhead at destination
- **Direction-aware:** exit point chosen by relative position of target
  - Target right of source → exit right, enter left (normal flow)
  - Target left of source → exit left, enter right (recycle/return)
  - Target above/below → exit top/bottom (vertical runs, instrument connections)
  - Signal edges → always exit instrument bubble bottom, enter top

### SVG layer structure
Every generated SVG must use named `<g>` layers in this order (bottom to top):
1. `<g id="layer-piping">` — process stream edges
2. `<g id="layer-signals">` — signal/instrument edges (dashed)
3. `<g id="layer-equipment">` — process equipment symbols
4. `<g id="layer-instruments">` — instrument bubble symbols
5. `<g id="layer-mechanical">` — valves, relief devices
6. `<g id="layer-connectors">` — off-page connectors
7. `<g id="layer-labels">` — all text annotations

Every symbol group element must carry data attributes:
- `data-tag` — the tag label
- `data-kind` — node kind string
- `data-area` — area/drawing reference

### Positions
- Claude-extracted positions are approximate (±10% error expected)
- Engineer drag positions saved to `canvas.json` — these override Claude positions
- Canvas.json positions survive re-extraction (pass0 delete does not clear canvas.json)

---

## File structure rules
- All project files under `EngineeringHub/projects/<pid>/`
- Source PDFs → `source_docs/`
- Cached extractions → `cache/`
- Exports → `exports/`
- Canvas state → `canvas.json`
- Review decisions → `review.json`
- Manifest → `project.json`
- Main project data → `<pid>.espx` (YAML)

## API rules
- All routes return JSON (except `/canvas/<pid>` HTML and `/api/projects/<pid>/source/<f>`)
- 404 returns `{"error": "..."}` never HTML
- Never return 500 without printing traceback to terminal
- Cache hits must print `Cache hit: ...` to terminal

## Python rules
- Flask only — no additional web frameworks
- No async Flask — keep synchronous (streaming via anthropic SDK is OK)
- Requirements: flask, anthropic, pyyaml, python-dotenv only
- No numpy, pandas, or heavy dependencies

## Node kind reference (complete)
**INSTRUMENT_KINDS:** transmitter · controller · indicator · recorder · switch · analyzer · element
**PROCESS_KINDS:** vessel · separator · pump · heat_exchanger · compressor · column · reactor · absorber · adsorption · filter · meter
**MECHANICAL_KINDS:** valve · checkvalve · relief (topology edges only — no VIDS/enableSim)
**CONNECTOR_KINDS:** off_page_connector (topology only, carries to_drawing on its edges)

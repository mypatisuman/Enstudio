# PlantSketch — P&ID Digitization Framework

## Purpose

This framework governs how PlantSketch converts a scanned P&ID 
into structured, connected, renderable data. It applies to every 
step: extraction → classification → connection → layout → export.

Every company's P&IDs follow the same underlying structure. 
The company conventions file overrides the tag-level details, 
but the STRUCTURE is universal.

---

## 1. What a P&ID Actually Is

A P&ID is NOT a flat list of tags. It is a layered graph:

```
LAYER 1 — Process Topology (the backbone)
  Equipment connected by process pipes in flow order.
  This is the main horizontal line: vessel → pump → HX → reactor → separator
  
LAYER 2 — Control Loops (the nervous system)
  Instruments monitoring process variables, controllers computing output,
  control valves acting on the process. Connected by signal lines.
  Each loop: sensor → transmitter → controller → final element
  
LAYER 3 — Mechanical (the plumbing)
  Hand valves, check valves, drain valves, vent valves, spectacle blinds.
  These sit inline on pipes but carry no signal. They exist for maintenance.
  
LAYER 4 — Safety (the protection)
  Relief valves, rupture discs, safety instrumented functions.
  These connect to process equipment but only act in emergencies.
```

### Visual Convention (universal)

```
              Equipment    Equipment    Equipment
                 │            │            │
    ─────────────●────────────●────────────●──────── Main process line
                 │            │            │
              ┌──┴──┐     ┌──┴──┐     ┌──┴──┐
              │ FT  │     │ TT  │     │ PT  │      Transmitters (spokes)
              └──┬──┘     └──┬──┘     └──┬──┘
                 │            │            │        Signal lines (dashed)
              ┌──┴──┐     ┌──┴──┐     ┌──┴──┐
              │ FIC │     │ TIC │     │ PIC │      Controllers
              └──┬──┘     └──┬──┘     └──┬──┘
                 │            │            │
              ┌──┴──┐     ┌──┴──┐     ┌──┴──┐
              │ FCV │     │ TCV │     │ PCV │      Control valves (on pipe)
              └─────┘     └─────┘     └─────┘
```

---

## 2. ISA Tag Decoding (Universal)

Every ISA tag encodes its meaning. The FIRST LETTER is the measured 
variable. Subsequent letters are the function.

### First Letter = What is measured
| Letter | Variable | Example Tags |
|---|---|---|
| F | Flow | FT, FI, FIC, FE, FCV, FIT |
| P | Pressure | PT, PI, PIC, PE, PCV, PIT, DPIT |
| T | Temperature | TT, TI, TIC, TE, TCV, TIT |
| L | Level | LT, LI, LIC, LE, LCV, LIT, LG |
| A | Analyzer/Composition | AT, AI, AIC, AE, AIT |
| Q | Quantity/Quality | QT, QI, QIC |
| D | Density/Differential | DT, DPI, DPIT |
| S | Speed/Safety | ST, SI, SIC |
| W | Weight | WT, WI, WIC |
| V | Vibration | VT, VI |
| H | Hand (manual) | HV, HC, HIC |
| X | Unclassified/On-Off | XV, XS, XA |
| E | Voltage/EMF | EY, EI |
| Z | Position | ZT, ZI, ZIC |

### Function Letters = What it does
| Letter(s) | Function | Category | Layer |
|---|---|---|---|
| T | Transmitter | transmitter | 2 - spoke below |
| I | Indicator | indicator | 2 - spoke below |
| IT | Indicating Transmitter | transmitter | 2 - spoke below |
| IC | Controller | controller | 2 - below transmitter |
| C | Controller | controller | 2 - below transmitter |
| E | Element/Sensor | element | 2 - inline or spoke |
| S, SH, SL | Switch (high/low) | switch | 2 - spoke below |
| A, AH, AL | Alarm (high/low) | alarm | 2 - at controller |
| AHH, ALL | Alarm (high-high/low-low) | alarm | 2 - at controller |
| Y | Relay/Compute/Convert | relay | 2 - between devices |
| R | Recorder | recorder | 2 - at controller |
| V | Valve | final_element | 1 - inline on pipe |
| G | Gauge/Glass | indicator | 2 - spoke from vessel |
| L | Light/Lamp | alarm | 2 - at panel |

### Decoding Examples
| Tag | Decode | Category | Layer |
|---|---|---|---|
| FT-1012 | Flow Transmitter | transmitter | spoke below pipe |
| PIC-3001 | Pressure Indicating Controller | controller | below transmitter |
| TCV-2103 | Temperature Control Valve | final_element | inline on pipe |
| LG-1501 | Level Gauge | indicator | spoke from vessel |
| PSV-4001 | Pressure Safety Valve | safety | on vessel top |
| HV-1057 | Hand Valve | mechanical | inline, hidden |
| EY-1006 | Voltage Relay | relay | at controller |
| DPIT-1027 | Differential Pressure Indicating Transmitter | transmitter | spoke |
| FIT-1505 | Flow Indicating Transmitter | transmitter | spoke |
| AL-4008A | Alarm Low | alarm | at panel |
| HP-1001 | — | UNKNOWN — company specific | check conventions |
| HT-1504 | — | UNKNOWN — could be "Heat Trace" | check conventions |

---

## 3. Tag Quality Rules

### Valid Tag Pattern
```
PREFIX-NNNN or PREFIX-NNNNx
where PREFIX = 1-5 uppercase letters (ISA code)
      NNNN = 3-5 digits (loop/sequence number)
      x = optional suffix (A, B, /A, /B)
```

### Quality Flags
| Pattern | Issue | Action |
|---|---|---|
| TAG-XXXX | Placeholder — OCR couldn't read | Flag for review, exclude from connections |
| TAG-XXX | Incomplete number | Flag for review |
| TAG (no number) | Bare prefix — likely partial OCR | Flag for review |
| Duplicate tags | Same tag on multiple nodes | Merge or flag |
| PUMP HEAD, COMP BASE | Description, not a tag | Reclassify as note, not equipment |
| RECYCLE, FEED | Stream label, not equipment | Exclude from layout |

### Auto-fix Rules
1. If tag matches "PREFIX" with no dash or number → mark as `quality: incomplete`
2. If tag contains "XXX" → mark as `quality: placeholder`
3. If tag matches a full English word (PUMP, REACTOR, RECYCLE) → mark as `quality: description`
4. Nodes with `quality != ok` are excluded from auto-connect and arrange-process

---

## 4. Classification Framework

For EVERY extracted node, determine its layer using this priority:

```
1. Company conventions file (if exists)
   → conventions.get_kind_for_tag(tag) 
   → conventions.get_valve_layer(tag)

2. ISA first-letter decode (universal)
   → Parse tag prefix using Section 2 tables
   → Determine: measured variable + function → category + layer

3. Kind field from extraction
   → If Claude labeled it as "valve", "transmitter", etc.
   → Map to palette kind

4. Default assumptions
   → Unrecognized valve with no signal → isolation (Layer 3, hidden)
   → Unrecognized valve with signal → control (Layer 2, shown)
   → Unrecognized instrument → transmitter (Layer 2)
   → Unrecognized equipment → vessel (Layer 1)
```

### Classification Output
Every node gets these fields:
```json
{
  "tag": "FT-1012",
  "pid_layer": 2,
  "category": "transmitter",
  "measured_variable": "flow",
  "function": "transmitter",
  "palette_kind": "ft",
  "valve_layer": null,
  "quality": "ok",
  "parent_equipment": "E-101",
  "loop_number": "1012"
}
```

---

## 5. Connection Framework

### Connection Sources (in priority order)
1. **Extracted edges** — from Pass 1 topology extraction
2. **Studio connections** — from Pass 2.5 pipe run extraction
3. **Loop inference** — ISA tag number grouping
4. **Equipment_ref** — instrument → equipment links
5. **Arrange Process** — Claude reasoning with engineering skill

### Universal Connection Rules

**Process connections (Layer 1):**
- Equipment → Equipment via process pipe
- Control valve inline on process pipe (splits pipe into two segments)
- Flow direction: left to right (or as specified in conventions)

**Signal connections (Layer 2):**
- Transmitter → Controller (signal)
- Controller → Control Valve (signal)
- Element → Transmitter (signal, short)
- Switch → Safety valve or trip (signal)

**Instrument-to-Equipment association:**
```
Priority 1: equipment_ref field (explicit)
Priority 2: Loop number matching
  FT-1012 loop 1012 → find equipment with tag ~10xx
Priority 3: Drawing/area proximity
  Same area + nearest equipment by position
Priority 4: Claude reasoning via arrange-process
```

### Connection Validation
- Every control valve must have exactly 2 process connections
- Every transmitter should have 1 signal connection (to controller)
- Every controller should have 1-2 signal connections (from transmitter, to valve)
- No equipment should have more than 6 process connections
- No self-loops
- No duplicate edges

---

## 6. Layout Framework

### Level of Detail

```
ZOOM LEVEL 1 — Plant Overview (fit all)
  Show: Area blocks as colored rectangles
  Hide: Individual equipment
  Navigate: Click area → zoom to Level 2

ZOOM LEVEL 2 — Area View (one process section)
  Show: Equipment on process line, control valves
  Hide: Instruments, mechanical valves
  Navigate: Click equipment → zoom to Level 3

ZOOM LEVEL 3 — Detail View (individual equipment)
  Show: Everything — equipment, instruments, valves, signals
  Navigate: Full interaction
```

### Layout Algorithm

```
FOR EACH area/drawing group:

  STEP 1 — Place process equipment (Layer 1)
    - Horizontal line at Y = bandY
    - Left to right in process flow order
    - Use topological sort on process edges
    - Spacing: 200px between equipment
    - Equipment with no process edges: grid at end of row

  STEP 2 — Place control valves (Layer 1)
    - FCV, TCV: inline on process pipe, between connected equipment
    - PCV: on vertical spoke below main line (Y = bandY + 60)
    - LCV: on vertical spoke below vessel liquid outlet

  STEP 3 — Place instruments (Layer 2)
    - Transmitters: Y = bandY + 120, X = parent equipment X
    - Controllers: Y = bandY + 200, X = midpoint(transmitter, valve)
    - Indicators: Y = bandY + 120, X = parent equipment X + offset
    - Elements: Y = bandY + 80, near parent (inline on spoke)
    - Multiple instruments on same equipment: spread horizontally

  STEP 4 — Place mechanical items (Layer 3)
    - Hand valves: inline on process pipe, small spacing
    - Check valves: inline, small spacing
    - Hidden by default — positions assigned but not rendered

  STEP 5 — Place safety items (Layer 4)
    - PSV/PRV: Y = bandY - 60, above vessel (top nozzle)
    - Rupture disc: next to PSV
    - Hidden by default in standard view

  STEP 6 — Route edges
    - Process pipes: horizontal routing (L-shaped or straight)
    - Signal lines: vertical routing (drop from equipment to instrument)
    - Safety connections: vertical up from equipment to PSV
```

### Area Ordering

```
Use company conventions flow order if available.
Otherwise, infer from tag numbers:
  Area 0xx = Feed/Storage (leftmost)
  Area 1xx = Feed treatment
  Area 2xx = Heat exchange
  Area 3xx = Reaction
  Area 4xx = Separation/Product
  Area 5xx = Product handling
  Area 8xx-9xx = Utilities (below main process)
```

---

## 7. Rendering Rules

### Node Sizing by Layer
| Layer | Node Size | Label Size | Opacity |
|---|---|---|---|
| 1 - Equipment | 80×60 px | 10px bold | 1.0 |
| 1 - Control Valve | 60×45 px | 9px | 1.0 |
| 2 - Transmitter | 50×50 px (circle) | 8px | 0.9 |
| 2 - Controller | 50×50 px (circle+line) | 8px | 0.9 |
| 2 - Indicator | 40×40 px | 7px | 0.8 |
| 3 - Hand Valve | 40×30 px | 7px | 0.6 (when shown) |
| 4 - Relief Valve | 40×40 px | 7px | 0.7 (when shown) |

### Edge Styling by Type
| Type | Stroke | Width | Dash | Arrow |
|---|---|---|---|---|
| Process pipe | #475569 | 2px | solid | filled |
| Signal line | #3b82f6 | 1.5px | 6,3 | filled |
| Safety connection | #dc2626 | 1px | 4,2 | open |
| Mechanical (hidden) | #94a3b8 | 1px | 2,2 | none |

### View Presets
| Preset | Layer 1 | Layer 2 | Layer 3 | Layer 4 |
|---|---|---|---|---|
| Process Only | Equipment + pipes | — | — | — |
| Process + Control | Equipment + pipes | Instruments + signals | — | — |
| Full P&ID | Everything | Everything | Everything | Everything |
| Safety Review | Equipment | Safety instruments | — | Safety devices |

---

## 8. Data Quality Dashboard

After extraction, show these metrics:

```
TAG QUALITY
  ✓ Valid tags: XXX / YYY (XX%)
  ⚠ Placeholder (XXX): NN tags
  ⚠ Incomplete (no number): NN tags
  ⚠ Duplicate: NN tags
  ✗ Unrecognized prefix: NN tags → [list]

CONNECTION QUALITY
  ✓ Connected nodes: XXX / YYY (XX%)
  ⚠ Dangling equipment: NN
  ⚠ Dangling instruments: NN
  ⚠ Dangling valves: NN

LOOP COMPLETENESS
  ✓ Complete loops: NN
  ⚠ Missing final element: NN
  ⚠ Missing measurement: NN
  ⚠ Orphan transmitters: NN

CLASSIFICATION
  Layer 1 (Process): NN equipment, NN control valves
  Layer 2 (Control): NN instruments
  Layer 3 (Mechanical): NN hand/check/misc valves
  Layer 4 (Safety): NN PSV/PRV, NN SIS devices
  Unclassified: NN → [list prefixes]
```

---

## 9. Company Conventions Integration

The conventions file OVERRIDES Section 2 defaults at the tag level:

```python
def classify_node(tag, kind, conventions=None):
    """Universal classification with company override."""
    
    # Step 1: Tag quality check
    quality = check_tag_quality(tag)
    if quality != 'ok':
        return {'quality': quality, 'layer': 0, 'category': 'flagged'}
    
    # Step 2: Company conventions (highest priority)
    if conventions:
        result = conventions.classify(tag)
        if result:
            return result
    
    # Step 3: ISA first-letter decode
    prefix = extract_prefix(tag)
    isa_result = isa_decode(prefix)
    if isa_result:
        return isa_result
    
    # Step 4: Kind field from extraction
    if kind in KNOWN_KINDS:
        return kind_to_classification(kind)
    
    # Step 5: Default
    return {'layer': 1, 'category': 'equipment', 'kind': 'vessel_v'}
```

---

## 10. Implementation Checklist

### In Extraction (main.py)
- [ ] Apply tag quality rules to every extracted tag
- [ ] Classify every node using Section 4 framework
- [ ] Set `pid_layer`, `category`, `measured_variable`, `quality`
- [ ] Exclude `quality != ok` from auto-connect
- [ ] Prepend company conventions to Claude prompts

### In Editor (editor.html)
- [ ] Layout uses Section 6 algorithm (area-based, tiered)
- [ ] Layer visibility uses Section 4 classification (not hardcoded)
- [ ] View presets match Section 7 table
- [ ] Node sizing varies by layer
- [ ] Edge styling varies by type
- [ ] Data quality dashboard in status bar

### In Export (svg_pid.py, etc.)
- [ ] SVG layers match the 4-layer model
- [ ] Default export = Layer 1 + Layer 2
- [ ] Full export = all layers
- [ ] Node sizing and opacity per Section 7

### In Company Conventions (adapters/company.py)
- [ ] Parse conventions.md into classification overrides
- [ ] Inject into every step: extraction, classification, layout, export
- [ ] Unknown prefixes flagged in data quality dashboard

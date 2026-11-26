# P&ID Development & Rendering Rules
# Based on: ISA-5.1, Perry's, Lipták's, and industry P&ID practice
# For PlantSketch rendering engine

---

## PART 1: P&ID SHEET ANATOMY

### 1.1 What a P&ID Sheet Contains
A P&ID sheet shows four categories of items:
- Process equipment (vessels, exchangers, pumps, reactors)
- Piping and flow conductors (process lines, utility lines)
- Instruments and control devices (transmitters, controllers, valves)
- Signal and connection lines (instrument signals, interlocks)

### 1.2 Sheet Organization
- Title block: drawing number, plant name, area, revision
- Main body: process equipment and piping, left-to-right flow
- Legend: only on legend sheets, not repeated on every sheet
- Notes: specific to that sheet, numbered
- Off-page connectors: arrows with destination drawing number
- Equipment data: design conditions in data boxes near equipment

### 1.3 Types of P&ID Sheets
- Legend P&ID: symbol definitions, applies to entire project
- System P&ID: one process system per sheet (most common)
- Network P&ID: utility distribution systems
- Interarea P&ID: connections between plant areas
- Detail P&ID: zoomed-in complex equipment (reactor internals)

### 1.4 Drawing Limits
- Maximum 3-5 major equipment items per sheet
- One process SECTION per sheet
- Crossing lines minimized (max 2-3 unavoidable crossings)
- Equipment spacing allows room for instrumentation

---

## PART 2: EQUIPMENT ARRANGEMENT (50 Rules)

### 2.1 General Flow Rules
R1. Process flows LEFT to RIGHT (primary direction)
R2. Gas/vapor flows UPWARD when vertical
R3. Liquid flows DOWNWARD when vertical (gravity)
R4. Feed enters from LEFT edge of sheet
R5. Product exits from RIGHT edge of sheet
R6. Utilities enter from BOTTOM
R7. Vent/relief exits from TOP
R8. Drain exits from BOTTOM

### 2.2 Equipment Positioning
R9. Major equipment on a horizontal CENTERLINE (process grade)
R10. Equipment drawn at relative ELEVATION when elevation matters
R11. Pumps drawn BELOW vessels (suction from bottom nozzle)
R12. Compressors at GRADE level (same Y as vessels)
R13. Overhead condensers ABOVE columns
R14. Reboilers BELOW columns (or beside, connected to bottom)
R15. Air coolers ABOVE grade (elevated, fans below)
R16. Relief valves ABOVE the vessel they protect
R17. Filters INLINE on process pipe

### 2.3 Equipment Spacing
R18. Minimum clear space between equipment for instrument spokes
R19. Equipment with many instruments needs more horizontal space
R20. Parallel equipment (A/B) stacked VERTICALLY at same X
R21. Spare equipment shown with dashed border or "(spare)" label
R22. Packaged/skid equipment inside a dashed boundary box

### 2.4 Stream Topology Rules
R23. Parallel feed streams at DIFFERENT Y levels, merge at reactor/mixer
R24. Product streams SPLIT at separator: gas UP/RIGHT, liquid DOWN/RIGHT
R25. Recycle stream returns from downstream to upstream, drawn as RETURN PATH
R26. Bypass stream: branch AROUND equipment, rejoin downstream
R27. Purge/vent: small branch from process to vent system
R28. Drain: small branch from low point to drain system
R29. Sample: small branch from process to analyzer/sample point

### 2.5 Standard Configurations
R30. COMPRESSOR TRAIN: suction KO drum → compressor → aftercooler → discharge KO drum
R31. PUMP ARRANGEMENT: suction source → isolation valve → pump → check valve → isolation valve
R32. COLUMN SYSTEM: feed → column (overhead: condenser → reflux drum → reflux pump; bottom: reboiler → bottoms pump)
R33. REACTOR SYSTEM: feed preheater → reactor → product cooler → separator
R34. SEPARATION TRAIN: cooler → HP separator → flash drums → filters → pumps → collection
R35. HEAT EXCHANGE: process on one side, utility on other; countercurrent default
R36. STORAGE: tank → pump → metering → process (batch) or tank → gravity feed (continuous)

### 2.6 Piping Rules
R37. Process pipe shown as THICK SOLID line (2-3pt)
R38. Utility pipe shown as THIN SOLID line (1pt) with service label
R39. Pipe size noted at changes: 6"-PG-2001 (size-service-number)
R40. Reducers shown at pipe size changes
R41. Pipe slope indicated by arrow when gravity flow
R42. Steam tracing shown as parallel thin line along pipe
R43. Insulation shown as cross-hatching or label

### 2.7 Valve Rules
R44. Isolation valves (HV, XV) at EACH equipment inlet and outlet
R45. Check valve DOWNSTREAM of every pump discharge
R46. Control valve with BYPASS (hand valve + 2 block valves) unless noted
R47. Drain valve at every low point in piping
R48. Vent valve at every high point in piping
R49. Relief valve on every pressurized vessel and blocked-in section
R50. Spectacle blind at maintenance boundaries

---

## PART 3: INSTRUMENTATION RULES (50 Rules)

### 3.1 ISA-5.1 Tag Structure
R51. Tag format: FIRST-LETTER + FUNCTION-LETTERS + LOOP-NUMBER
R52. First letter = measured variable (F=flow, P=pressure, T=temp, L=level, A=analyzer)
R53. Function letters = instrument function (T=transmitter, I=indicator, C=controller, V=valve, E=element)
R54. Loop number = unique per control loop (parallel or serial numbering)
R55. Suffix A/B = parallel/redundant instruments (not parallel equipment)

### 3.2 Instrument Symbol Shapes (ISA-5.1-2024)
R56. CIRCLE = field-mounted instrument (accessible)
R57. CIRCLE with HORIZONTAL LINE = control room panel-mounted
R58. CIRCLE with DASHED border = software/DCS function
R59. SQUARE = local panel-mounted (inaccessible, behind panel)
R60. DIAMOND = safety instrumented system (SIS) function
R61. HEXAGON = shared display / multi-variable
R62. Size: instrument bubbles 10-12mm diameter on standard drawing

### 3.3 Instrument Placement
R63. Transmitter (xT): on VERTICAL SPOKE below or beside process pipe
R64. Controller (xIC): BELOW transmitter, connected by signal line
R65. Indicator (xI): on SHORT SPOKE from pipe (small circle)
R66. Element (xE): INLINE on pipe or at TAP POINT (thermowell, orifice plate)
R67. Recorder (xR): at panel level, connected by signal
R68. Switch (xS): on spoke, between process and alarm/trip
R69. Control valve: INLINE on process pipe (not on spoke)
R70. Safety valve: on VERTICAL NOZZLE above vessel

### 3.4 Signal Line Types
R71. Electrical signal: DASHED line (- - - -)
R72. Pneumatic signal: DASHED line with cross marks (- x - x -)
R73. Software/data link: DASHED line with circles (- o - o -)
R74. Capillary (filled system): THIN SOLID line
R75. Hydraulic: DASHED line with diamonds
R76. Fieldbus: THICK DASHED line (double width)
R77. Wireless: ZIGZAG symbol on signal line

### 3.5 Control Loop Representation
R78. Complete loop: element → transmitter → controller → final element
R79. Signal flow: MEASUREMENT flows up/toward controller; CONTROL flows down/toward valve
R80. Controller output to valve: signal line from controller to valve actuator
R81. Cascade: primary controller output → setpoint of secondary controller
R82. Feedforward: measurement → computing element → added to controller output
R83. Ratio: flow measurement → ratio station → controller setpoint
R84. Split range: one controller → two valves (each handles part of range)
R85. Override/select: multiple controllers → selector → one valve

### 3.6 Alarm and Safety
R86. Alarm suffixes: H (high), L (low), HH (high-high), LL (low-low)
R87. Alarms are NOT separate physical devices — they are annotations on the controller
R88. Trip/interlock: DIAMOND symbol (SIS), separate from BPCS
R89. Safety function: separate tag numbering from BPCS (e.g., SIS-PT-101)
R90. Fire & gas: separate symbol system (typically triangle)

### 3.7 Specific Instrument Patterns
R91. FLOW LOOP: FE (orifice, inline) → FT (spoke below) → FIC (below FT) → FCV (inline on pipe)
R92. PRESSURE LOOP: PT (spoke from pipe/vessel) → PIC (below PT) → PCV (inline or on branch)
R93. TEMPERATURE LOOP: TE (thermowell, inline) → TT (spoke) → TIC (below) → TCV (on utility side of HX)
R94. LEVEL LOOP: LT (on vessel side nozzle) → LIC (below LT) → LCV (on vessel outlet pipe)
R95. ANALYZER LOOP: AE (sample probe) → sample system → AT (analyzer) → AIC (controller)

### 3.8 Non-Physical Items (DO NOT render as equipment)
R96. Alarms (xAH, xAL, xAHH, xALL) = annotation on controller, not a device
R97. Relays/compute (xY) = software function in DCS, not a physical device
R98. Hand switches (HS) = panel pushbutton, not field device
R99. Shared display = one screen showing multiple variables, not separate devices
R100. Configuration notes (setpoint, range, action) = text annotations

---

## PART 4: RENDERING ENGINE RULES

### 4.1 Two-Level Rendering

LEVEL 1: Process Flow Overview (PFD-level)
- Show only STREAM-DEFINING equipment (~20 items)
- Equipment where streams merge, split, or transform
- No instruments, no auxiliary equipment
- Streams labeled with flow direction
- Parallel feeds at different Y levels converging

LEVEL 2: P&ID Detail (per drawing/area)
- Show 3-5 major equipment with full instrumentation
- All instruments as ISA circles on vertical spokes
- Control valves inline with bypass arrangement
- Signal routing: vertical preferred
- Equipment data boxes

### 4.2 Stream-Based Layout Algorithm

Step 1: IDENTIFY STREAMS
- Parse edges to find continuous paths from source to sink
- Label each stream: type (process/utility/safety), phase
- Identify merge points (multiple inputs → one output)
- Identify split points (one input → multiple outputs)
- Identify recycle (downstream → upstream connection)

Step 2: ASSIGN STREAM Y-LEVELS
- Primary process stream: Y = 0 (centerline)
- Parallel feed #1 (e.g., H2): Y = -150 (above center)
- Parallel feed #2 (e.g., CO2): Y = +150 (below center)
- Feeds converge at merge equipment: both lines route to Y = 0
- After split: product stream Y = 0, recycle Y = -200, vent Y = -300
- Utility streams: Y = +500 (well below process)
- Safety/relief: Y = -400 (well above process)

Step 3: PLACE EQUIPMENT ON STREAMS (X positions)
- Left-to-right in process order
- X spacing = 250px between major equipment
- Merge point X: where parallel feeds converge
- Split point X: where products diverge
- Equipment in same unit operation group: tight spacing (150px)
- Equipment in different sections: gap (400px)

Step 4: ADD INSTRUMENTS (per Lipták)
- For each equipment, enumerate its instruments
- Place transmitters on vertical spokes below (Y + 120)
- Place controllers below transmitters (Y + 200)
- Place control valves INLINE (same Y as equipment)
- Place indicators on short spokes (Y + 80)
- Place elements inline on pipe
- Spread multiple instruments horizontally, centered on parent

Step 5: ROUTE EDGES
- Process pipes: horizontal at stream Y level
  - L-shaped routing for Y-level changes
  - Avoid crossing other pipes (route around)
- Signal lines: VERTICAL from instrument to pipe/valve
  - Prefer vertical routing (up from valve to controller)
  - Minimize horizontal signal runs
- Utility lines: vertical from utility band up to equipment
  - Small connection, not full pipe routing

### 4.3 Per-Drawing Detail View

When showing one area in detail:
- Only that area's equipment + instruments
- Off-page connectors at LEFT and RIGHT edges
- Full control loop representation
- Equipment data boxes visible
- Pipe spec callouts on major lines
- Valve details (fail position, size)
- Note section at bottom

### 4.4 Color Coding
- Process pipe: #475569 (dark grey), solid, 2px
- Signal line: #1565C0 (blue), dashed 6,3, 1.5px
- Utility pipe: #0d9488 (teal), solid, 1.5px
- Safety/relief: #dc2626 (red), solid, 1.5px
- Recycle: #7c3aed (purple), solid, 2.5px
- Instrument bubble fill: #E3F2FD (light blue)
- Equipment fill: #F1F5F9 (light grey)
- Valve fill: #FFF3E0 (light orange)
- Safety device fill: #FDE2E2 (light red)

### 4.5 Symbol Sizing
- Major equipment: 80x60px (vessels, reactors, columns)
- Heat exchangers: 100x40px (elongated)
- Pumps: 50x50px
- Compressors: 60x60px
- Control valves: 40x30px (bowtie)
- Instrument bubbles: 30px diameter (circle)
- Indicators: 20px diameter (small circle)

---

## PART 5: LAYOUT RULES (machine-readable YAML)

```yaml
# PlantSketch Layout Configuration
# Edit these values to change rendering behavior

backbone:
  y: 400
  x_start: 200
  x_step: 250
  direction: left-to-right

sheet:
  max_equipment_per_view: 5
  equipment_spacing_px: 250
  section_gap_px: 400
  margin_px: 100

streams:
  primary_y: 0
  parallel_feed_offset: 150
  merge_converge_to: 0
  product_y: 0
  recycle_y: -200
  vent_y: -300
  utility_y: 500
  safety_y: -400

control_valve:
  placement: inline_on_pipe
  pcv_placement: inline_on_pipe
  x_offset: 80

utility:
  dy_below_backbone: 600
  x_step: 250

instruments:
  above_valve:
    controller_dy: -100
    transmitter_dy: -180
  below_equipment:
    transmitter_dy: 120
    indicator_dy: 120
    indicator_dx: 60
    controller_dy: 200
  multiple_spread: 50
  bubble_diameter: 30
  bubble_shape: circle
  bubble_mask_padding: 6

equipment:
  vessel_size: [80, 60]
  vessel_shape: rectangle
  vessel_mask_padding: 12
  hx_size: [100, 40]
  hx_shape: rectangle
  hx_mask_padding: 10
  pump_size: [50, 50]
  pump_shape: circle
  pump_mask_padding: 8
  compressor_size: [60, 60]
  compressor_shape: circle
  compressor_mask_padding: 10
  reactor_size: [80, 70]
  reactor_shape: rectangle
  reactor_mask_padding: 15
  column_size: [50, 120]
  column_shape: rectangle
  column_mask_padding: 12
  valve_size: [40, 30]
  valve_shape: diamond
  valve_mask_padding: 8
  filter_size: [50, 50]
  filter_shape: rectangle
  filter_mask_padding: 8

edge_colors:
  process: "#475569"
  signal: "#1565C0"
  utility: "#0d9488"
  safety: "#dc2626"
  recycle: "#7c3aed"

edge_widths:
  process: 2
  signal: 1.5
  utility: 1.5
  safety: 1.5
  recycle: 2.5

edge_dash:
  process: "solid"
  signal: "6,3"
  utility: "solid"
  safety: "solid"
  recycle: "solid"

fills:
  equipment: "#F1F5F9"
  instrument: "#E3F2FD"
  valve: "#FFF3E0"
  safety: "#FDE2E2"

area_order:
  - feed
  - metering
  - compression
  - preheat
  - reactor
  - separation
  - product

area_order_full:
  - H2 FEED GAS DELIVERY
  - CO2 FEED GAS DELIVERY
  - H2 FEED GAS METERING
  - FEED GAS METERING
  - RECYCLE COMPRESSOR
  - PDC H2 COMPRESSOR
  - FEED GAS PREHEAT
  - REACTOR
  - REACTOR R-302
  - REACTOR R-302 PRODUCT
  - SEPARATOR & PRODUCT COLLECTION
  - GAS ANALYTICS & SAMPLING
  - VENT HEADER

edge_routing:
  process: horizontal_first
  signal: vertical_only
  utility: vertical_from_utility_band
```

# PlantSketch — Process Reconstruction Skill
# Updated with engineering gap analysis from CTP project

## What the Tool Sees vs What an Engineer Knows

The extraction gives us a flat list of tags grouped by area.
An engineer sees the same tags and instantly knows the process 
flow, because chemical plants follow universal patterns.

This skill teaches PlantSketch those patterns.

---

## GAP 1: Process Flow Sequence

### Problem
Equipment is grouped by area but not connected in flow order.
V-151, C-150, HE-153, V-152 are all in "RECYCLE COMPRESSOR" 
but PlantSketch doesn't know V-151 feeds C-150.

### Rule: Standard Equipment Sequences

Every process area follows one of these patterns. When 
extraction misses individual pipe connections, use the 
PATTERN to infer the flow:

**Feed Storage & Delivery:**
```
Storage tank → Vaporizer/HX → Pressure regulator → Metering
TK-052 → X-101 → (PCV) → (FIT)
```

**Compression Section (Perry's Ch.10):**
```
Suction drum → Compressor → Aftercooler → KO drum → [next stage or discharge]
V-151 → C-150 → HE-153 → V-152
```
ALWAYS this order. A compressor NEVER precedes its suction drum.

**Preheat Train:**
```
Cold feed → HX-1 → HX-2 → HX-3 → [reactor]
```
Multiple HXs in series. If tags have A/B suffix (HE-202A, 
HE-202B), they are PARALLEL — same duty, redundant.

**Feed/Effluent Heat Exchange (Perry's Ch.11):**
```
Cold feed IN → [shell side] → hot feed OUT → reactor
Hot product IN → [tube side] → cooled product OUT → separator
```
HE-202 and HE-203 have TWO process streams passing through.
The hot side comes BACK from the reactor. This creates a 
COUNTER-FLOW in the layout — one line goes right (to reactor), 
one comes left (from reactor).

**Reactor Section:**
```
Preheated feed → Reactor → Interstage cooler → Reactor-2
R-301 → HE-302 → R-302
```
For exothermic reactions (Fischer-Tropsch, methanation, 
oxidation), temperature control is CRITICAL. Expect:
- Multiple TEs on the reactor (temperature profile)
- PIT for reactor pressure
- TIC controlling cooling medium flow via TCV

**Separation Section (Perry's Ch.15-18):**
```
Reactor effluent → Product cooler → HP separator → 
Flash drums (staged depressurization) → Filters → 
Product pumps → Collection vessels
```
```
HE-3501 → V-401 → V-402 → V-403 → F-3501 → P-4501 → V-4501
```

**Utility Systems:**
```
Cooling: Chiller → Glycol header → Process HXs → Return
Heating: Heater → Hot oil header → Process HXs → Return
Air: Compressor → Dryer → Header → Users
Vent: Equipment vents → Vent header → V-9501 → Atmosphere/flare
```
Utilities are CLOSED LOOPS — they serve the process but are 
separate from it.

### Implementation
When arranging process, check each area for pattern match:
1. Does the area name contain "compressor"? → Apply compression pattern
2. Does it contain "preheat"? → Apply preheat train pattern
3. Does it contain "reactor"? → Apply reactor section pattern
4. Does it contain "separator" or "product"? → Apply separation pattern
5. Does it contain "glycol|oil|air|vent|electrical"? → Utility layer

---

## GAP 2: Recycle Loops

### Problem
The recycle compressor takes unreacted gas from the separator 
back to the reactor inlet. This is the most important feature 
of the CTP plant — it determines conversion and selectivity. 
PlantSketch doesn't show process loops.

### Rule: Detect and Render Recycle
If a compressor section's suction drum (V-151) connects to a 
separator section's gas outlet, AND the compressor discharge 
connects to a reactor feed, that is a RECYCLE LOOP.

Render as: a process pipe from separator → compressor section → 
back to preheat/reactor. Show with a distinct color or line 
style (e.g., thicker line or labeled "RECYCLE").

### Detection Heuristic
1. Find compressor suction drum (V-1xx in compressor area)
2. Find separator gas outlet (from V-4xx in separator area)
3. If both exist and tag numbers suggest same loop → recycle

---

## GAP 3: Utility vs Process Separation

### Problem
Glycol, hot oil, instrument air, vent header are rendered as 
process areas at the same level as reactor and separator. 
They should be subordinate.

### Rule: Utility Layer
Areas whose names match these patterns are UTILITY, not PROCESS:
- glycol, cooling, chiller
- hot oil, thermal fluid, heating
- instrument air, plant air, compressed air
- vent, flare, relief header
- electrical, power, UPS, MCC

Utility areas render BELOW the main process flow, in a 
separate horizontal band. Process pipes from utilities to 
process equipment render as vertical dashed lines (utility 
supply/return), not solid process pipes.

---

## GAP 4: Feed/Effluent Heat Exchangers

### Problem
HE-202A/B are feed/effluent exchangers with TWO process 
streams. Current rendering shows them as single inline items.

### Rule: Dual-Stream HX
When two equipment items in different areas both connect to 
the same HX (e.g., preheat feed connects to HE-202 AND 
reactor product connects to HE-202), render the HX with:
- Two connection ports on each side (hot in/out, cold in/out)
- Or a distinctive symbol showing counter-flow

### Detection
HXs in the "preheat" area that also appear referenced in 
"reactor product" connections → dual-stream.

---

## GAP 5: Safety Layer Connections

### Problem  
PSV on reactors and vessels are safety-critical but unconnected.
They should connect to the equipment they protect AND to the 
vent header.

### Rule: PSV Placement
1. PSV-xxx → find equipment in same area with matching number
   PSV-313 → protects equipment in area 3xx
2. Connect PSV to equipment (vertical line UP from vessel top)
3. Connect PSV outlet to vent header (V-9501/9502 in VENT area)
4. Render PSV ABOVE its equipment, not below

---

## GAP 6: Instrument-Equipment Association

### Problem
381 instruments with 0 equipment_ref. The extraction doesn't 
know which instrument monitors which equipment.

### Rule: ISA Number Association
The first 2-3 digits of an instrument's loop number match 
the equipment area:
- TE-3003 → area 30xx → on R-301 (reactor)
- PIT-3002 → area 30xx → on R-301 (reactor)
- FIT-1503 → area 15xx → on C-150 (compressor) discharge
- LIT-4001 → area 40xx → on V-401 (separator)

Association priority:
1. Exact equipment_ref (if populated)
2. Loop number first 2 digits match equipment first 2 digits
3. Same area + instrument function matches equipment type:
   - LT/LI/LIC → vessel (level measurement)
   - TT/TI/TIC → reactor or HX (temperature)
   - PT/PI/PIC → vessel or compressor (pressure)
   - FT/FI/FIC → pipe between equipment (flow)

---

## GAP 7: Non-Equipment Tags

### Problem
"PUMP HEAD", "COMP BASE", "HE-AUTO", "N2-cyl-A/B", 
"HE-202A_tag", "F-XXXX" are in the equipment list but 
are not real process equipment.

### Rule: Tag Cleanup
| Pattern | Action |
|---|---|
| Full English words (PUMP HEAD, COMP BASE) | Reclassify as note |
| Tags ending in _tag, _label, _note | Reclassify as annotation |
| N2-cyl, O2-cyl, gas cylinder tags | Reclassify as utility |
| F-XXXX, X-XXX (placeholder) | Already filtered by quality |
| HE-AUTO, AUTO-xxx | Reclassify as control system note |
| RECYCLE, FEED, PRODUCT | Reclassify as stream label |
| REF-xxxx (refrigeration) | Reclassify as utility equipment |
| PNL-xxx (panel) | Reclassify as non-physical |

---

## Process Reconstruction Prompt

When calling Claude for arrange-process, use this enhanced prompt:

```
You are a senior process engineer reconstructing a {process_type} 
plant from extracted P&ID data.

COMPANY CONVENTIONS:
{conventions_text}

PROCESS DESCRIPTION (from drawing titles):
{drawing_titles_and_areas}

STANDARD PROCESS PATTERNS:
- Feed storage → vaporizer → regulator → metering
- Suction drum → compressor → aftercooler → KO drum
- Cold feed → preheat HX train → reactor
- Reactor → interstage cooler → second reactor
- Product cooler → HP separator → flash drums → filters → pumps → collection
- Utility systems are closed loops (supply → users → return)

ALREADY CONNECTED:
{connected_pairs}

EQUIPMENT BY AREA (connect these using the patterns above):
{equipment_by_area}

RULES:
1. Apply the standard pattern for each area type
2. Within an area, connect equipment in tag-number order 
   unless the pattern dictates otherwise
3. Pumps ALWAYS follow vessels: V-xxx → P-xxx
4. HXs with A/B suffix are PARALLEL (connect both to same 
   upstream/downstream)
5. Compressor section: suction drum → compressor → cooler → KO drum
6. Reactor section: preheat → reactor → cooler → next reactor
7. Separator section: cooler → HP sep → flash → filter → pump → collection
8. Utility areas: closed loops, separate from main process
9. Recycle: if compressor suction connects to separator gas outlet, 
   show the recycle loop
10. Cross-area connections: preheat feeds reactor, reactor feeds separator

RETURN JSON:
{
  "connections": [{from_tag, to_tag, kind, reasoning}],
  "process_sections": [
    {
      "area": "RECYCLE COMPRESSOR",
      "pattern": "compression",
      "flow_order": ["V-151", "C-150", "HE-153", "V-152"],
      "description": "Recycle gas compression with aftercooling"
    }
  ],
  "recycle_loops": [
    {
      "from_area": "SEPARATOR",
      "to_area": "RECYCLE COMPRESSOR", 
      "description": "Unreacted gas recycle"
    }
  ],
  "utility_connections": [
    {from_tag: "X-890", to_tag: "HE-302", kind: "utility", 
     medium: "glycol cooling"}
  ]
}
```

---

## Layout Rules (Updated)

### Main Process (top section, left to right)
```
FEED → METERING → COMPRESSION → PREHEAT → REACTOR → SEPARATION → PRODUCT
```

### Utility (bottom section, below main process)
```
GLYCOL    HOT OIL    INSTRUMENT AIR    VENT HEADER    ELECTRICAL
```

### Within Each Area (horizontal band)
```
Tier 0: Equipment in flow order (left to right)
Tier 1: Connected instruments (120px below parent equipment)
Tier 2: Controllers (200px below)
Hidden:  Mechanical valves, safety (positions assigned, not shown)
```

### Cross-Area Connections
- Process flow: horizontal lines between area bands
- Recycle: labeled line from separator back to compressor
- Utility: vertical dashed lines from utility band up to equipment

---

## Rendering Quality Checklist

After reconstruction, verify:
☐ Every area has equipment connected in a physically valid sequence
☐ No vessel follows a pump (pump always AFTER vessel)
☐ No compressor follows its aftercooler (compressor before cooler)
☐ HXs with dual service show both connections
☐ Reactors have temperature instruments connected
☐ Separators have level instruments connected
☐ Compressors have suction drum and discharge KO drum
☐ Utility areas are below main process
☐ Recycle loop is visible if compressor section exists
☐ PSV connected to vessel above, relief to vent header
☐ No "PUMP HEAD", "COMP BASE" or other descriptions in equipment

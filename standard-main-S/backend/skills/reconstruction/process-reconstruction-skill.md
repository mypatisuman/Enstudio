# PlantSketch — Process Reconstruction Skill

## Purpose
Given extracted P&ID tag data (equipment, instruments, valves), reconstruct the process connections that an engineer would draw. This skill is used when pipe run extraction is incomplete — equipment and instruments were identified but not all connections.

## Core Engineering Rules

### 1. Equipment Numbering Reveals Process Sections
ISA/company tag conventions encode the process:
- First digit = process area/unit (1xx = Unit 1, 2xx = Unit 2...)
- Equipment letter = type (V=vessel, P=pump, E=exchanger, R=reactor, T=tower/column, C=compressor, D=drum, A=air cooler, M=motor)

Equipment with the SAME area number belongs to the SAME process section:
- V-101, P-101, E-101, R-101 are all in Unit 1
- V-201, P-202, E-202 are all in Unit 2

### 2. Universal Process Flow Patterns
These patterns appear in every chemical plant:

**Reactor Section:**
Feed vessel → Feed pump → Feed/effluent HX → Reactor → Product cooler → Separator
V-101 → P-101 → E-101 → R-101 → E-102 → V-102

**Distillation Section:**
Feed → Column → Overhead condenser → Reflux drum → Reflux pump → (back to column)
         → Reboiler → (back to column)
         → Bottoms pump → downstream
V-201 → T-201 → E-201 (condenser) → V-202 (reflux drum) → P-201 (reflux pump)
                → E-202 (reboiler)
                → P-202 (bottoms pump)

**Compression Section:**
Suction drum → Compressor → Aftercooler → Discharge drum
V-301 → C-301 → E-301 → V-302

**Utility patterns:**
- Air coolers (A-xxx) cool process streams — always inline after reactors or compressors
- Motors (M-xxx) drive pumps or compressors — M-901 drives P-901

### 3. Valve Placement Rules (ISA First-Letter Code)

Valves sit IN process lines between equipment. The ISA number reveals WHERE:

**Control valves (FCV, PCV, TCV, LCV):**
- FCV = Flow Control Valve — in main process pipe, controls flow
- PCV = Pressure Control Valve — on vessel outlet or compressor discharge
- TCV = Temperature Control Valve — on cooling/heating medium line
- LCV = Level Control Valve — on vessel liquid outlet

The valve number links to its controller:
- FCV-1012 is controlled by FIC-1012 (same loop number)
- PCV-1500 is controlled by PIC-1500
- TCV-2103 is controlled by TIC-2103

**Where the valve goes:**
- FCV-1012: between the two equipment items in flow loop 1012. Look at FIC-1012's equipment_ref — the valve is on that equipment's outlet line
- LCV-1457: on the liquid outlet of the vessel that LIC-1457 measures level on
- PCV-1500: on the gas outlet of the vessel that PIC-1500 measures pressure on
- TCV-1051: on the utility (steam/CW) inlet to the heat exchanger that TIC-1051 measures

**Isolation/shutdown valves (XV, SDV, BDV, ESD):**
- XV = on/off valve, same loop number as its switch (e.g., XV-1022 controlled by XS-1022 or part of SIS)
- XV sits in the SAME line as the control valve with matching area number
- SDV/BDV = safety shutdown/blowdown — on vessel inlet/outlet

**Relief valves (PSV, PRV):**
- PSV = Pressure Safety Valve — on vessel top nozzle, relieves to flare
- PRV = Pressure Relief Valve — same function
- PSV number matches the vessel: PSV-1032 protects vessel in area 10xx

### 4. Connecting Valves to Equipment

Step 1: Find the valve's control loop
- FCV-1012 → loop 1012 → controller FIC-1012 → measurement FIT-1012
- FIT-1012 has equipment_ref = E-101 → the valve is on E-101's process line

Step 2: Determine upstream/downstream
- FCV (flow): inline in pipe, between upstream and downstream equipment
- LCV (level): on vessel liquid outlet → vessel → LCV → downstream equipment
- PCV (pressure): on vessel gas outlet → vessel → PCV → downstream
- TCV (temperature): on utility side of HX → utility source → TCV → HX utility inlet

Step 3: Place the valve
- Find the two equipment items the valve sits between
- Create: upstream_equipment → valve → downstream_equipment

### 5. Connecting Dangling Equipment

For each dangling equipment item, find where it belongs:

**Pumps (P-xxx):** Always downstream of a vessel or column bottoms
- P-101 → look for V-101 or T-101 bottoms → P-101 connects V-101 → P-101
- If no matching vessel, pump feeds the next equipment: P-101 → E-101

**Heat exchangers (E-xxx):** Inline in process, between two other items
- E-101 → look at what's upstream and downstream with similar numbers
- E-101 sits between P-101 (upstream) and R-101 (downstream)

**Vessels/Drums (V-xxx, D-xxx):** Process holdup between operations
- V-102 → sits after reactor section (R-101) and before next section

**Columns (T-xxx):** Central to distillation section
- T-201 → has condenser (E-201), reboiler (E-202), reflux drum (V-202)
- Connect: feed → T-201, E-201 → V-202 → P-201 → T-201 (reflux)

**Air coolers (A-xxx):** Cool process streams
- A-501 → inline after a reactor or compressor in area 5

**Motors (M-xxx):** Drive equipment
- M-901 drives P-901, M-902 drives C-902, etc.
- Connect: M-xxx → driven equipment (signal connection, not process)

## Prompt Template

Use this prompt when calling Claude to arrange process:

```
You are a senior process engineer reconstructing P&ID connections 
from extracted tag data. Apply standard process engineering logic 
and ISA tag numbering conventions.

ALREADY CONNECTED (do not duplicate):
{connected_pairs}

DANGLING EQUIPMENT (need process pipe connections):
{dangling_equipment_with_kind_and_drawing}

DANGLING VALVES (need to be inserted in process lines):
{dangling_valves_with_drawing}

CONTROL LOOPS (from ISA tag inference):
{loops_with_controller_measurement_valve}

INSTRUMENT-EQUIPMENT REFERENCES:
{instruments_with_equipment_ref}

RULES:
1. Equipment numbering: first digit(s) = unit/area. Same area = same process section.
2. Flow patterns: vessel → pump → HX → reactor → cooler → separator → column
3. Valve placement:
   - FCV sits in main process line at its loop's equipment
   - LCV on vessel liquid outlet
   - PCV on vessel gas outlet  
   - TCV on utility side of heat exchanger
   - XV in same line as matching control valve
   - PSV/PRV on vessel top, relieves to flare header
4. Pump is ALWAYS downstream of a vessel: V-101 → P-101
5. HX is inline: P-101 → E-101 → R-101
6. Motor drives equipment: M-901 → P-901 (signal, not process)
7. Column has condenser+reflux drum+reboiler connected in standard pattern
8. Do NOT connect items from different area numbers unless they are 
   clearly feed/product transfers (different unit connections)
9. Every valve must sit BETWEEN two equipment items — never dangling

For each connection, state:
- from_tag: upstream equipment
- to_tag: downstream equipment  
- kind: "stream" (process) or "signal" (instrument/motor)
- reasoning: one sentence explaining WHY (e.g., "P-101 is the feed pump for V-101 based on matching area number and pump-downstream-of-vessel pattern")

Return ONLY JSON:
{
  "connections": [
    {"from_tag": "V-101", "to_tag": "P-101", "kind": "stream", "reasoning": "..."},
    ...
  ],
  "process_sections": [
    {"area": "100", "flow_order": ["V-101","P-101","E-101","R-101","E-102","V-102"], "description": "Reactor feed and product section"}
  ]
}
```

## Validation After Reconstruction

After Claude returns connections, validate:
1. Every valve has exactly 2 process connections (one in, one out)
2. No equipment has more than 4 process connections (physically unreasonable)
3. No duplicate edges
4. No self-loops
5. Process sections form directed acyclic graphs (no circular process flow, except column reflux)
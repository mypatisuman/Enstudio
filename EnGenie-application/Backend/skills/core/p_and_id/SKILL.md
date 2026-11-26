# SKILL.md — P&ID Reading Strategy
# EngineeringStudio core skill · ISA-5.1 / ISO 10628
# Updated: April 2026 — learnings from CTP Demo 157-2 (19-page, 817-node plant)

---

## Your Task

Read this engineering drawing and extract all process equipment, instruments,
and connections. Return structured JSON. Be exhaustive — miss nothing.

---

## Critical Classification Rules

### Three categories — do NOT mix them

**Category 1 — DCS Instruments** (in `instruments` section)
These have a DCS tag, historian signal, alarm setpoint.

Examples: FT-101, TIC-201, PT-302, AIT-9005, PSHH-301, JS-9004, NA-9010

**Category 2 — Process Equipment** (in `equipment` section)
These have a simulation block, duty, mass/energy balance.

Examples: E-101, R-302, V-101, P-1101, K-115, C-150, TK-052

**Category 3 — Mechanical Inline Items** (in `nodes` only — NOT instruments or equipment)
Mechanical apparatus. No DCS tag. No alarm setpoints. No simulation block.

Examples: HV-1057 (hand valve), NRV-101 (check valve), PSV-101 (relief),
BPR-3101 (back pressure regulator), XV-101 (block valve), spectacle blinds

Put these in `nodes` with kind=valve, checkvalve, or relief.

---

## Control Valve Distinction

A control valve assembly has TWO parts:
- Valve body (mechanical) → node, kind=valve — NOT in instruments
- Controller/positioner (instrument) → instruments, type=controller or transmitter

Example: FCV-101 (valve body) = node kind=valve. FIC-101 (controller) = instrument type=controller.

---

## Instrument Types — Use ONLY these 7

Return ONLY these exact strings in `instruments.type`:

| Type | Use for |
|---|---|
| `transmitter` | FT, PT, TT, LT, AT, AIT, DT, WT and all measurement transmitters |
| `controller` | FIC, PIC, TIC, LIC, AIC, IC, loading stations, positioners |
| `indicator` | FI, PI, TI, LI, gauges, lights, annunciators, speed indicators, status displays |
| `recorder` | FR, PR, TR, LR, AR |
| `switch` | FSH/PSL/TSHH/LSLL, relays (JY), alarms (JA/AL/EHH), solenoids, shutdown, ESD |
| `analyzer` | QT, pH, gas chromatographs, combustible gas detectors, online analyzers |
| `element` | FE, TE, PE, orifice plates, thermowells, RTDs, pitot tubes, sensing elements |

NEVER return: flow_transmitter, temperature_controller, pressure_indicator,
high_alarm_tag, relay, annunciator, gauge, thermowell, gas_analyser, alarm_hihi.
Map these to the correct type above.

---

## ISA Tag Prefix Quick Reference

| Prefix | Variable | Notes |
|---|---|---|
| F | Flow | FT=transmitter, FIC=controller, FE=element, FSH=switch |
| P | Pressure | PT=transmitter, PIC=controller, PSV=relief (mechanical), PSHH=switch |
| T | Temperature | TT=transmitter, TIC=controller, TE=element, TSHH=switch |
| L | Level | LT=transmitter, LIC=controller, LSH=switch, LG=indicator |
| A | Analyzer | AIT=transmitter, AIC=controller, AE=element |
| H | Hand | HV=hand valve (mechanical/kind=valve), HIC=controller |
| J | Electrical | JS=switch, JY=switch (relay), JA=switch (alarm) |
| N | Annunciator | NA=indicator, NL=indicator, NLA=indicator |
| Y | Computation | YI=indicator (status), YC=controller |
| Z | Position | ZT=transmitter, ZIC=controller |
| E | Power | EHH=switch (high-high alarm) |

---

## Equipment Kind Reference

| Kind | Use for |
|---|---|
| vessel | tanks, drums, accumulators, surge vessels, TK/V tags |
| separator | flash drums, KO drums, three-phase separators, scrubbers |
| heat_exchanger | shell & tube, plate, reboilers, condensers, fired heaters, air coolers, glycol chillers, hot oil packages |
| pump | centrifugal, gear, metering, charge pumps |
| compressor | centrifugal, reciprocating, recycle compressors |
| reactor | fixed bed, CSTR, PFR, jacketed reactors |
| column | distillation, absorption, stripping columns |
| filter | strainers, coalescers, bag filters, mist eliminators |
| meter | Coriolis, magnetic flowmeter (when shown as equipment item) |

---

## Panel Instruments (PNL-100 and similar)

Panel-mounted instruments are real DCS instruments — include them in `instruments`:
- JS (job switch) → type: switch
- JY (relay) → type: switch
- JA (alarm) → type: switch
- NA (annunciator) → type: indicator
- NL, NLA (lights) → type: indicator
- IC (indicating controller) → type: controller
- AIT (analyzer transmitter) → type: transmitter
- AE (analyzer element) → type: element

Set equipment_ref to the panel tag (e.g. PNL-100).

---

## Connection Reading — be exhaustive

**Every visible pipe run must appear as an edge.** Miss no connections.

### Process pipe runs (edges.kind = stream | recycle | bypass)
Follow every line from source to destination:
- Main process flows (feed → reactor → separator → etc.)
- Utility connections: steam, cooling water, nitrogen, fuel gas, flare header
- Bypass lines around equipment (kind=bypass)
- Recycle/return lines back upstream (kind=recycle)
- Drain and vent lines to headers

For each pipe run, capture what is visible on the drawing:
- `label`: the line designation if printed (e.g. `6"-PG-2001-A1B`, `4"-HVO-1003`)
- `from_nozzle` / `to_nozzle`: nozzle label if printed on equipment (N1, N2, inlet, outlet, drain)
- `fluid`: process fluid from legend or tag (PG=process gas, HVO=heavy vac oil, CW=cooling water)
- `line_size`: nominal diameter from line designation or callout (4", 6", DN100)
- `line_class`: piping class if shown (150#, 300#, A1B)

### Signal connections (edges.kind = signal)
Add a signal edge for each instrument loop connection:
- Transmitter → Controller: FT-101 → FIC-101
- Controller → Final element: FIC-101 → FCV-101
- Switch → Solenoid/valve: PAHH-301 → XV-301
- Analyzer → DCS: AIT-501 → AIC-501

Signal edges do NOT carry fluid or line_size.

### Off-page connectors
When a pipe run exits the drawing (continues to another sheet):
- Add a node with kind=`off_page_connector`, label=`→ <drawing_number>`
- Add the edge from the last equipment to the off_page_connector node
- Set `to_drawing` on the edge to the destination drawing number

Example: pipe `6"-PG-2001` exits to drawing 157-2-140:
```json
{"id": "n99", "label": "→ 157-2-140", "kind": "off_page_connector", "drawing": "157-2-130"}
```
Edge: `{"from": "n38", "to": "n99", "kind": "stream", "label": "6\"-PG-2001", "to_drawing": "157-2-140"}`

### Connection direction
Always record upstream → downstream (flow direction).
Use arrow symbols, flow tags, or process knowledge to determine direction.
When direction is ambiguous, use left→right, top→bottom as default.

For multi-page PDFs: use the drawing title as area for equipment on that page.

---

## Output Format — JSON only, no fences, no explanation

{
  "nodes": [
    {"id": "n1", "label": "E-101", "kind": "heat_exchanger"},
    {"id": "n2", "label": "FT-101", "kind": "transmitter"},
    {"id": "n3", "label": "HV-1057", "kind": "valve"}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "kind": "stream", "label": "S-001"},
    {"from": "n2", "to": "n3", "kind": "signal"}
  ],
  "instruments": {
    "FT-101": {
      "type": "transmitter",
      "equipment_ref": "E-101",
      "range_lo": 0.0,
      "range_hi": 500.0,
      "units": "kg/h",
      "alarm_hi": null,
      "alarm_hihi": null,
      "alarm_lo": null,
      "alarm_lolo": null,
      "fail_position": null,
      "confidence": 0.92
    }
  },
  "equipment": {
    "E-101": {"area": "FEED GAS PREHEAT", "description": "feed preheater"}
  },
  "connections": [
    {"from_tag": "TK-052", "to_tag": "E-101", "fluid": "liquid", "line_size": "4in", "id": "S-001"}
  ]
}

---

## Confidence

- 0.90-1.0: tag clearly readable, type unambiguous
- 0.70-0.89: tag readable, type inferred
- 0.50-0.69: partially readable or uncertain
- ≤0.85: always for PSV, PAHH, TAHH, LAHH, ESD (safety — force engineer review)
- null for alarm limits unless printed on drawing

---

## What NOT to do

- Do NOT put HV, NRV, BPR, PSV, block valves in instruments
- Do NOT use descriptive type names (flow_transmitter, pressure_switch_high, etc.)
- Do NOT skip panel instruments (JS, JY, NA, NL) — they are real DCS tags
- Do NOT infer alarm limits — null unless visible on drawing
- Do NOT add Perry physics parameters — those come from enableSim

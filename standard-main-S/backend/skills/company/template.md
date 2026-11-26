# {{COMPANY_NAME}} — P&ID Conventions

> Fill in this file once per company. PlantSketch uses these
> conventions for extraction, rendering, layer filtering,
> connections, and layout. Leave blank if standard ISA.

## 1. Equipment Tag Prefixes
| Equipment Type | Standard ISA | This Company | Notes |
|---|---|---|---|
| Heat Exchanger | E- | | |
| Vessel / Drum | V- | | |
| Pump | P- | | |
| Compressor | C- | | |
| Column / Tower | T- | | |
| Reactor | R- | | |
| Tank | TK- | | |
| Filter | F- | | |
| Air Cooler | A- | | |
| Motor | M- | | |

### Additional Equipment Types
| Prefix | Full Name | Category | Notes |
|---|---|---|---|
| | | vessel / hx / pump / reactor / separation / other | |

## 2. Valve Classification
> DEFAULT RULE: Valves with NO signal connection are treated
> as isolation/mechanical valves (hidden by default).
> Valves WITH signal connections are control valves (shown).
> Override below if needed.

| Prefix | Full Name | Layer | Notes |
|---|---|---|---|
| FCV- | Flow Control Valve | control | |
| PCV- | Pressure Control Valve | control | |
| TCV- | Temperature Control Valve | control | |
| LCV- | Level Control Valve | control | |
| HV- | Hand Valve | hand | |
| CK- | Check Valve | check | |
| NRV- | Non-Return Valve | check | |
| PSV- | Pressure Safety Valve | relief | |
| PRV- | Pressure Relief Valve | relief | |
| RV- | Relief Valve | relief | |
| XV- | On/Off Valve | isolation | |
| SDV- | Shutdown Valve | isolation | |
| BDV- | Blowdown Valve | isolation | |
| MOV- | Motor Operated Valve | isolation | |

### Additional Valve Types
| Prefix | Full Name | Layer | Notes |
|---|---|---|---|
| | | control / hand / check / relief / isolation | |

## 3. Instrument Tag Prefixes
> Standard ISA first-letter codes apply unless overridden.

| Prefix | Standard ISA Meaning | This Company | Notes |
|---|---|---|---|
| F | Flow | | |
| P | Pressure | | |
| T | Temperature | | |
| L | Level | | |
| A | Analyzer | | |
| Q | Quantity | | |

### Additional Instrument Types
| Prefix | Full Name | Category | Notes |
|---|---|---|---|
| | | transmitter / indicator / controller / switch | |

## 4. Tag Numbering Convention
- First digit meaning: (e.g., area, unit, system)
- Example breakdown: V-1201 → ?

Answer:

## 5. Drawing Numbering
- Format: (e.g., PID-101, 965429-120-16, DWG-001)
- How to extract drawing number from filename:

Answer:

## 6. Line Numbering
- Format: (e.g., 6"-PG-2001)
- Encoding: size-service-number

Answer:

## 7. Process Flow
- Main flow direction: left-to-right / right-to-left
- Feed enters from: left / top
- Product exits to: right / bottom

Answer: left-to-right

## 8. Rendering Preferences
- Valve placement:
  - Control valves (FCV/TCV): inline on process line
  - Pressure valves (PCV): on branch/spoke from main line
  - Level valves (LCV): on vessel liquid outlet (below)
- Instrument placement:
  - Transmitters: spoke below process line
  - Controllers: below transmitters
  - Indicators: spoke below or beside equipment
- Signal line style: dashed blue
- Process pipe style: solid dark

## 9. Control System
- DCS platform:
- Safety system:
- Fieldbus: HART / FF-H1 / Profibus

## 10. Default Assumptions
> These apply when information is missing from extraction.

- Unrecognized valve with no signal → isolation (hidden)
- Unrecognized valve with signal → control (shown)
- Unrecognized instrument → transmitter
- Unrecognized equipment → vessel

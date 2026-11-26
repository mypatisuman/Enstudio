# AIR COMPANY — P&ID Conventions
# Project: 157-2 CO2-to-Paraffins (CTP) Demo Plant

> This file teaches PlantSketch how to read, classify, 
> connect, and render AIR COMPANY P&IDs.

## 1. Equipment Tag Prefixes
| Equipment Type | Standard ISA | This Company | Notes |
|---|---|---|---|
| Heat Exchanger | E- | X-, HE-, HTX- | X = compact exchanger, HE = standard, HTX = heat transfer unit |
| Vessel / Drum | V- | V- | Standard. V-xxx used throughout |
| Pump | P- | P- | Standard |
| Compressor | C- | C- | Standard. C-101, C-150 |
| Column / Tower | T- | — | Not used in this project |
| Reactor | R- | R-, GLR-, REACTOR- | GLR = Glass-Lined Reactor, REACTOR = full-word tag |
| Tank | TK- | TK- | Standard. TK-051, TK-052, TK-053 |
| Filter | F- | F- | Standard. F-3101, F-3501, F-4001 etc. |
| Air Cooler | A- | — | Uses REF- for refrigeration instead |
| Motor | M- | — | Not tagged separately |
| Separator | — | S- | S-xxx for separators |
| Quench Cooler | — | QC- | Process equipment — inline cooler after reactor |
| Glass-Lined Separator | — | GLS- | Specialty glass-lined vessel |
| Glass-Lined Reactor | — | GLR- | Specialty glass-lined reactor |
| Refrigeration Unit | — | REF- | Packaged chiller/cooler |
| Reverse Osmosis | — | RO- | Water treatment |
| Reboiler/Kettle | — | RK- | Reboiler |
| Cooler | — | CO- | Simple cooler |
| Panel | — | PNL- | Instrument/control panel |
| Recycle marker | — | RECYCLE- | Not equipment — recycle stream label |

### Equipment Kind Mapping (for PlantSketch palette)
| Company Prefix | Editor Kind | Symbol |
|---|---|---|
| X- | hx_st | Shell & tube HX |
| HE- | hx_st | Shell & tube HX |
| HTX- | hx_st | Shell & tube HX |
| V- | vessel_v | Vertical vessel |
| TK- | tank_atm | Atmospheric tank |
| P- | pump_cent | Centrifugal pump |
| C- | comp_cent | Centrifugal compressor |
| R- | cstr | Reactor |
| GLR- | cstr | Reactor (glass-lined) |
| REACTOR- | cstr | Reactor |
| F- | filter_pf | Filter |
| QC- | hx_st | Quench cooler (renders as HX) |
| S- | vessel_v | Separator |
| GLS- | vessel_v | Glass-lined separator |
| REF- | cooling_tower | Refrigeration unit |
| RO- | membrane | RO unit |
| RK- | reboiler_k | Kettle reboiler |
| CO- | condenser | Cooler |
| PNL- | dcs | Control panel |

## 2. Valve Classification

> DEFAULT RULE: Valves with NO signal connection are treated 
> as isolation/mechanical valves (hidden by default).
> Valves WITH signal connections are control valves (shown).

| Prefix | Full Name | Layer | Notes |
|---|---|---|---|
| PCV- | Pressure Control Valve | control | Main control valve type in this plant |
| FCV- | Flow Control Valve | control | |
| TCV- | Temperature Control Valve | control | |
| LCV- | Level Control Valve | control | |
| FV- | Flow Valve | control | Company-specific, acts as flow control |
| PV- | Pressure Valve | control | Company-specific pressure control |
| PVC- | Pressure Valve Control | control | Variant of PCV |
| CV- | Control Valve | control | Generic control valve |
| ADV- | Actuated Diaphragm Valve | control | On/off control, often in reactor feed |
| SV- | Solenoid Valve | isolation | Emergency shutdown, SIS-driven |
| ORV- | Overflow Relief Valve | relief | Liquid overflow protection |
| PRV- | Pressure Relief Valve | relief | |
| PSV- | Pressure Safety Valve | relief | |
| RV- | Relief Valve | relief | |
| SRV- | Spring Relief Valve | relief | |
| PRR- | Pressure Relief (redundant) | relief | |
| HV- | Hand Valve | hand | Manual isolation |
| CK- | Check Valve | check | Non-return |
| NRV- | Non-Return Valve | check | |
| XV- | On/Off Valve | isolation | |

## 3. Instrument Tag Prefixes

> This plant uses standard ISA instrument codes.
> First letter = measured variable, subsequent = function.

| Prefix | Standard ISA Meaning | This Company | Notes |
|---|---|---|---|
| F | Flow | Same | FT, FI, FIC, FE |
| P | Pressure | Same | PT, PI, PIC, PIT |
| T | Temperature | Same | TT, TI, TIC, TIT |
| L | Level | Same | LT, LI, LIC, LIT |
| A | Analyzer | Same | AT, AI, AIT |
| Q | Quantity/Quality | Same | QT |
| D | Density/Differential | Same | DPI, DPIT |

### Instrument Function Codes
| Code | Meaning | Category |
|---|---|---|
| -T | Transmitter (FT, PT, TT) | transmitter |
| -I | Indicator (FI, PI, TI) | indicator |
| -IC | Controller (FIC, PIC, TIC) | controller |
| -IT | Indicating Transmitter | transmitter |
| -E | Element (FE, TE) | element |
| -SH | Switch High | switch |
| -SL | Switch Low | switch |
| -AH | Alarm High | alarm |
| -AL | Alarm Low | alarm |

### Company-Specific Instrument Prefixes

These prefixes are AIRCO-specific and not standard ISA-5.1. Each entry
documents *why* the convention exists and *when* it was learned, so
classification rules can be revised if the upstream practice changes.

> HT- convention: AIRCO uses HT (Hot Temperature) for
> the hot/utility side of dual-service heat exchangers.
> The process side uses standard TIT-xxA. The utility
> side uses HT-xxB. This is not standard ISA-5.1 —
> it is AIRCO's company shorthand. Learned from
> drawing 157-2-120 (FEED GAS PREHEAT), confirmed
> by engineer review May 2026.

| Prefix | Full Name | Category | Notes |
|---|---|---|---|
| HT- | Hot-side Temperature Indicator | indicator | B-side instrument on dual-service heat exchangers only. Monitors utility/hot return side temperature. No controller expected — local readout only. Pair: TIT-xxA (process side) ↔ HT-xxB (hot side) |

> JE/JT- convention: AIRCO uses J-prefix for power
> and energy measurements on electric heating elements.
> ISA first letter J = Power. These are monitoring-only
> instruments with no control loop. Learned from
> drawing 157-2-120 (FEED GAS PREHEAT), confirmed
> by engineer review May 2026.

| Prefix | Full Name | Category | Notes |
|---|---|---|---|
| JE- | Power/Energy Element | element | Electric heater power measurement element. J = Power (ISA). No controller expected — feeds historian only |
| JT- | Power Transmitter | transmitter | Electric heater power transmitter. Same family as JE. No controller expected |

> EY/TY/FY convention: AIRCO uses Y-suffix for relay,
> compute, and convert functions on instruments.
> ISA second letter Y = relay/compute/convert.
> These are non-physical DCS software functions —
> they exist in the control system but have no
> physical symbol on the P&ID.
> Learned from drawing 157-2-120 (FEED GAS PREHEAT),
> confirmed by engineer review May 2026.

| Prefix | Full Name | Category | Notes |
|---|---|---|---|
| EY- | Electric relay/compute | relay | Non-physical. ISA Y=relay. No controller expected. VIDS export only, not canvas |
| TY- | Temperature relay/compute | relay | Non-physical. Same family as EY |
| FY- | Flow relay/compute | relay | Non-physical. Same family as EY |

> SRV convention: AIRCO uses SRV for spring-loaded
> safety relief valves. Set point labeled on drawing.
> Learned from drawing 157-2-105 (CO2 FEED GAS
> DELIVERY), confirmed by engineer review May 2026.

| Prefix | Full Name | Layer | Notes |
|---|---|---|---|
| SRV- | Spring Relief Valve | relief | Safety layer. Render above protected equipment |

> FIC convention: AIRCO uses FIC (Flow Indicating
> Controller) interchangeably with FTC on some
> drawings. Both mean the same instrument — a flow
> controller with display. Treat as alias for FTC.
> Learned from drawing 157-2-120 (FEED GAS PREHEAT),
> confirmed by engineer review May 2026.

| Prefix | Full Name | Category | Notes |
|---|---|---|---|
| FIC- | Flow Indicating Controller | controller | Alias for FTC. Same classification |

> TW convention: AIRCO uses TW for thermowell
> temperature elements. TW = Temperature Well.
> Measurement-only, no controller expected.
> Already extracted in DB — adding classification.
> Learned from drawing 157-2-120 (FEED GAS PREHEAT),
> confirmed by engineer review May 2026.

| Prefix | Full Name | Category | Notes |
|---|---|---|---|
| TW- | Thermowell temperature element | element | T=temperature, W=well. No controller expected |

## 4. Tag Numbering Convention

- Format: PREFIX-XYYY where X = area, YY = sequence
- First digit groups:
  - 0xx = Feed gas storage & delivery
  - 1xx = Feed metering, preheat, recycle
  - 2xx = Heat exchange (preheat/cool)
  - 3xx = Reactor section
  - 4xx = Separation & product collection
  - 5xx = Product handling
  - 8xx = Vent, relief, flare
  - 9xx = Utilities, electrical
- Example: V-401 = Vessel, area 4 (separation), sequence 01
- Example: PCV-3001 = Pressure Control Valve, area 3 (reactor), loop 01

## 5. Drawing Numbering

- Format: 157-2-XXX
- 157 = project number
- 2 = revision/package number  
- XXX = drawing sequence number
- Drawing number encodes process section:
  - 100-109: Feed Gas Delivery (H2, CO2)
  - 110-114: Feed Gas Metering
  - 115-119: Recycle Compressor
  - 120-129: Feed Gas Preheat
  - 130-139: Reactor (R-301, R-302)
  - 140-149: Separator & Product Collection
  - 150-159: Gas Analytics & Sampling
  - 189-192: Utilities (glycol, hot oil, instrument air)
  - 195: Vent Header
  - 199: Electrical Cabinet

## 6. Line Numbering

- Format not fully standardized in this demo plant
- Process lines follow equipment numbering area

## 7. Process Flow

- Main flow direction: left-to-right
- Feed enters from: left (H2 and CO2 delivery)
- Product exits to: right (separator, collection)
- Process sequence:
  1. H2 Feed Gas Delivery → H2 metering
  2. CO2 Feed Gas Delivery → CO2 metering
  3. Mixed feed → Recycle compressor
  4. Compressed feed → Feed gas preheat
  5. Hot feed → Reactor R-301 → Reactor R-302
  6. Reactor effluent → Separator & product collection
  7. Tail gas → Analytics & sampling → Vent header
  8. Utilities support: glycol cooling, hot oil heating, instrument air

## 8. Rendering Preferences

- Valve placement:
  - PCV: on branch/spoke from main process line (pressure tap)
  - FV, FCV: inline on process line (flow control)
  - ADV: inline, actuated on/off (show as bowtie with actuator)
  - SV: inline, solenoid (show as bowtie, small)
  - ORV: on branch to drain/vent
- Instrument placement:
  - Transmitters (FT, PT, TT): spoke below process line
  - Controllers (FIC, PIC): below transmitters
  - Indicators (PI, TI): small spoke from process line
- Signal lines: dashed blue
- Process pipes: solid dark, 2px
- Color coding:
  - Red: safety/relief (PSV, ORV, SV)
  - Blue: instruments and signals
  - Green: control valves and controllers
  - Orange: heat exchange equipment

## 9. Control System

- DCS platform: Not specified in demo plant
- Safety system: SV (solenoid) driven, no separate SIS tagged
- Field instruments: Standard 4-20mA assumed
- No Foundation Fieldbus in this plant

## 10. Default Assumptions

> These apply when information is missing from extraction.

- Unrecognized valve with no signal → isolation (hidden)
- Unrecognized valve with signal → control (shown)
- Unrecognized instrument → transmitter
- Unrecognized equipment → vessel
- X-XXX tags (placeholder tags like X-XXX) → ignore or flag for review
- RECYCLE- tags → not equipment, stream label only
- Equipment on same drawing with sequential numbers → connected in series
- HT- tags with B suffix → indicator, layer 3
  (mechanical/monitoring), no loop controller expected
- JE-/JT- tags → element/transmitter, layer 2,
  no controller expected, utility category

> RT- convention: R = Ratio, T = Transmitter.
> Ratio transmitter — monitors flow ratios between
> streams. Measurement-only, no controller expected.
> Learned from drawings 157-2-111 and 157-2-140,
> confirmed by engineer review May 2026.

- RT- tags → ratio transmitter (R=Ratio, T=Transmitter),
  layer 2, measurement-only, no controller expected
- EY-/TY-/FY- tags → relay/compute, non-physical,
  VIDS export only, exclude from canvas
- SRV- tags → relief valve, safety layer,
  above protected equipment
- FIC- tags → controller, alias for FTC
- TW- tags → temperature element, no controller expected

# NEL P&ID Conventions
# Source: XPE2869 Symbol Key / Component Tag Key (page 2)

## Component Tag Key

| Prefix | Type | Kind |
|--------|------|------|
| A | Process Vessel | vessel |
| BPR | Back Pressure Regulator | relief_valve |
| CG | Combustible Gas Sensor | analyzer |
| CP | Circulation Water Pump | pump |
| CV | Check Valve | check_valve |
| DPS | Dewpoint Sensor | analyzer |
| EM | Electrolysis Cell Module | vessel |
| F | Filter | filter |
| FAN | Fan | compressor |
| FI | Flow Indicator | indicator |
| FS | Flow Sensor | transmitter |
| FSW | Flow Switch | switch |
| GB | Guard Bed | vessel |
| HTR | Electric Heater | heat_exchanger |
| HX | Heat Exchanger | heat_exchanger |
| IX | Ion Exchange | vessel |
| LS | Level Sensor | transmitter |
| LSW | Level Switch | switch |
| MV | Motorized Valve | control_valve |
| OR | Orifice | element |
| PI | Pressure Indicator | indicator |
| PR | Forward Pressure Regulator | control_valve |
| PSW | Pressure Switch | switch |
| PT | Pressure Transducer | transmitter |
| PV | Pneumatic Valve | control_valve |
| RV | Relief Valve | relief_valve |
| RS | Water Resistivity/Conductivity Sensor | analyzer |
| SV | Solenoid Valve | solenoid_valve |
| TAS | Thermally Actuated Switch | switch |
| TC | Thermocouple | element |
| TCV | Temperature Control Valve | control_valve |
| TE | Thermistor or RTD | element |
| V | Valve | hand_valve |

## Tag Suffix → Process Loop

| Suffix | Process Loop |
|--------|-------------|
| 0xx | Cell Stack |
| 1xx | Air and Control |
| 2xx | Oxygen / Water and Oxygen |
| 3xx | Hydrogen / Water and Hydrogen |
| 4xx | Nitrogen or Argon |
| 5xx | Feed Water |
| 6xx | Coolant Liquid |
| 8xx | Calibration Gas |

## Tag Format Notes

- Tags do NOT follow standard ISA hyphen format (e.g. "FT-101").
- Instead they use prefix directly concatenated with the loop number:
  SV303A, PT312, A200, CP205, HX203a, GB208a
- Suffix letters (A, B, a, b) after the number indicate duplicates or sub-units:
  A335A and A335B are two vessels in the same loop
  HX203a and HX203b are two sides of the same heat exchanger
- EM tags (Electrolysis Cell Modules) may have format EM00X where X is a letter.

## Examples

| Tag | Type | Loop |
|-----|------|------|
| A200 | Process Vessel | Oxygen/Water loop |
| A300a | Process Vessel | Hydrogen/Water loop |
| SV303A | Solenoid Valve | Hydrogen loop |
| PT312 | Pressure Transducer | Hydrogen loop |
| CP205 | Circulation Water Pump | Oxygen loop |
| HX203a | Heat Exchanger | Oxygen loop |
| GB208a | Guard Bed | Oxygen loop |
| F124A | Filter | Air and Control loop |
| EM001 | Electrolysis Cell Module | Cell Stack |

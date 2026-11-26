# PlantSketch → enableSim Configuration Builder

## The Gap

PlantSketch extracts TOPOLOGY (what connects to what).
enableSim needs TOPOLOGY + PARAMETERS (how each unit behaves).

```
PlantSketch (today)          enableSim needs
─────────────────            ──────────────────
✅ Equipment tags            ✅ Equipment tags
✅ Equipment types           ✅ Unit operation MODEL
✅ Connections               ✅ Connection TYPE (mass/heat/pressure)
✅ Instruments               ✅ Instrument ranges + alarms
✅ Control loops             ✅ PID tuning parameters
❌ Operating conditions      ✅ T, P, F, composition per stream
❌ Physical properties       ✅ Cp, rho, k₀, Ea per species
❌ Equipment sizing          ✅ V, A, D per equipment
❌ Reaction data             ✅ Stoichiometry, kinetics
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ PlantSketch                                          │
│                                                      │
│  Draw / Describe / Upload PDF                        │
│       │                                              │
│       ▼                                              │
│  espx (topology: nodes + edges + loops)              │
│       │                                              │
│       ├── VIDS → ENGRAM (tag database)               │
│       │                                              │
│       ├── YMPL (flat) → enableSim validate           │
│       │                                              │
│       └── NEW: enableSim Config Builder              │
│            │                                         │
│            ├── Step 1: Model Assignment               │
│            │   R-301 → CSTR model                     │
│            │   E-101 → HX_countercurrent model        │
│            │   V-401 → Flash model                    │
│            │                                         │
│            ├── Step 2: Parameter Collection            │
│            │   (from datasheets, Describe, or Claude) │
│            │   R-301: V=5m³, T=350°C, P=25bar         │
│            │   E-101: UA=5000 W/K, Tcw=25°C           │
│            │                                         │
│            ├── Step 3: Connection Classification       │
│            │   R-301→E-101: mass+heat (process pipe)  │
│            │   TIC-201→TCV-201: signal (control)      │
│            │                                         │
│            ├── Step 4: Matrix Block Generation         │
│            │   M_11 = CSTR block (7 params)           │
│            │   M_12 = coupling (mass flow k_12)       │
│            │                                         │
│            └── Step 5: Export .ympl with parameters   │
│                 → enableSim build → eigenvalues       │
│                 → HAZOP → alarm setpoints             │
│                 → back to ENGRAM                      │
└─────────────────────────────────────────────────────┘
```

## Step 1: Model Assignment

PlantSketch knows the equipment TYPE from extraction + conventions.
Map each type to an enableSim unit operation model:

| PlantSketch kind | enableSim Model | State Variables | Parameters |
|---|---|---|---|
| cstr, batch_reactor | CSTR | T, C_A, V | k₀, Ea, ΔH_rxn, V, ρ, Cp |
| pfr | PFR | T(z), C_A(z) | k₀, Ea, L, D, U |
| fixed_bed, fluidized_bed | CatalyticReactor | T, C_A, P | k₀, Ea, ε, dp, ρ_cat |
| hx_st, hx_plate, condenser | HX | T_hot, T_cold | UA, F_hot, F_cold, Cp |
| reboiler_k, reboiler_t | Reboiler | T, x_vapor | Q, F_feed, λ |
| vessel_v, vessel_h, flash_drum | Flash | T, P, L, x | F_in, z_feed, VLE params |
| knockout, accumulator | Drum | L, P | V, F_in, F_out |
| dist_tray, dist_packed | Column | T_n, x_n per stage | N_stages, α, R, F |
| pump_cent, pump_pd | Pump | P_out, F | η, ΔP, NPSH |
| comp_cent, comp_recip | Compressor | P_out, T_out, F | η, ratio, Cp/Cv |
| air_cooler, cooling_tower | AirCooler | T_out | UA, F_air, T_air |

### Implementation
```python
# In adapters/enablesim_config.py

MODEL_MAP = {
    'cstr': 'CSTR',
    'pfr': 'PFR', 
    'fixed_bed': 'CatalyticReactor',
    'hx_st': 'HX_CounterCurrent',
    'condenser': 'HX_Condenser',
    'reboiler_k': 'Reboiler',
    'vessel_v': 'Flash',
    'flash_drum': 'Flash',
    'knockout': 'Drum',
    'dist_tray': 'Column_Tray',
    'pump_cent': 'Pump',
    'comp_cent': 'Compressor',
    # ... map all 108 kinds
}

def assign_model(node, conventions=None):
    """Map PlantSketch node → enableSim model type."""
    kind = node['kind']
    # Company conventions can override
    if conventions:
        model = conventions.get_model_for_kind(kind)
        if model: return model
    return MODEL_MAP.get(kind, 'GenericBlock')
```

## Step 2: Parameter Collection

Three sources for parameters, in priority order:

### Source A: Datasheet Import (most reliable)
```
Upload a CSV/Excel datasheet with:
  Tag, Parameter, Value, Units
  R-301, Volume, 5.0, m³
  R-301, Design_Temp, 400, °C
  R-301, Design_Pressure, 30, barg
  E-101, UA, 5000, W/K
  TIC-201, Range_Hi, 400, °C
  TIC-201, Kp, 2.5, %/°C
```

### Source B: Describe (conversational)
User types in the Ask/Describe panel:
- "R-301 is a 5 cubic meter CSTR at 350°C, 25 bar"
- "E-101 has UA of 5000 W/K, cooling water at 25°C"
- "TIC-201 controls R-301 temperature, Kp=2.5, Ti=120s"

Claude extracts parameters and assigns to the right equipment.

### Source C: Claude Estimation (least reliable, useful for early design)
If no datasheet and user hasn't specified:
- Claude estimates reasonable parameters from:
  - Equipment type + size class
  - Process fluid (from line labels)
  - Operating pressure/temperature from instrument ranges
  - Perry's correlations for physical properties
  
This gives order-of-magnitude values for preliminary simulation.

### Parameter Template per Model
```yaml
# R-301 (CSTR)
model: CSTR
parameters:
  volume: {value: null, units: m³, source: null}
  temperature: {value: null, units: °C, source: null}
  pressure: {value: null, units: barg, source: null}
  feed_flow: {value: null, units: kg/h, source: null}
  feed_composition: {value: null, units: mol_frac, source: null}
  k0: {value: null, units: 1/s, source: null}
  Ea: {value: null, units: J/mol, source: null}
  delta_H: {value: null, units: J/mol, source: null}
  density: {value: null, units: kg/m³, source: null}
  Cp: {value: null, units: J/kg/K, source: null}
completeness: 0%  # 0/10 parameters filled
```

## Step 3: Connection Classification

PlantSketch edges are "process" or "signal". enableSim needs
more specific coupling types:

| Edge Type | PlantSketch | enableSim Coupling | Matrix Entry |
|---|---|---|---|
| Mass flow | process pipe | mass_coupling | F × (C_out - C_in) |
| Heat flow | process pipe between HX | heat_coupling | UA × ΔT |
| Pressure | process pipe to pump/comp | pressure_coupling | ΔP |
| Signal | signal line | control_coupling | Kp × e(t) |
| Bypass | bypass line | bypass_coupling | f × F_total |
| Recycle | recycle line | recycle_coupling | R × F_product |

### Implementation
```python
def classify_connection(edge, from_node, to_node):
    """Classify process pipe into enableSim coupling type."""
    if edge['connType'] == 'signal':
        return 'control_coupling'
    
    from_kind = from_node['kind']
    to_kind = to_node['kind']
    
    # HX connections carry heat
    if 'hx' in from_kind or 'hx' in to_kind:
        return 'heat_coupling'
    
    # Pump/compressor connections carry pressure
    if 'pump' in from_kind or 'comp' in from_kind:
        return 'pressure_coupling'
    
    # Default: mass flow
    return 'mass_coupling'
```

## Step 4: Matrix Block Generation

For each equipment node, generate the diagonal M_ii block.
For each connection, generate the off-diagonal M_ij block.

```python
def generate_cstr_block(params):
    """Generate M_ii for a CSTR.
    States: [T, C_A, V]
    """
    V = params['volume']
    T = params['temperature'] + 273.15  # to Kelvin
    F = params['feed_flow']
    k0 = params['k0']
    Ea = params['Ea']
    dH = params['delta_H']
    rho = params['density']
    Cp = params['Cp']
    R_gas = 8.314
    
    # Reaction rate at operating point
    k = k0 * exp(-Ea / (R_gas * T))
    
    # Jacobian (linearized around steady state)
    # dT/dt = F/V*(T_in-T) + dH*k*C_A/(rho*Cp) - UA*(T-Tc)/(rho*Cp*V)
    # dC_A/dt = F/V*(C_Ain-C_A) - k*C_A
    
    J = [
        [-F/V + dH*k*Ea*C_A/(rho*Cp*R_gas*T**2), dH*k/(rho*Cp), 0],
        [-k*Ea*C_A/(R_gas*T**2), -F/V - k, 0],
        [0, 0, -F/V]  # volume dynamics (if level control)
    ]
    return J

def generate_hx_block(params):
    """Generate M_ii for a heat exchanger.
    States: [T_hot_out, T_cold_out]
    """
    UA = params['UA']
    F_h = params['F_hot']
    F_c = params['F_cold']
    Cp_h = params['Cp_hot']
    Cp_c = params['Cp_cold']
    
    J = [
        [-F_h*Cp_h - UA, UA],
        [UA, -F_c*Cp_c - UA]
    ]
    return J
```

## Step 5: Export Enhanced YMPL

Extend the YMPL export to include parameters:

```yaml
schema_version: ympl-2.0
id: ctp
title: CO2-to-Paraffins Demo Plant
company: AIRCO

units:
  - tag: R-301
    model: CSTR
    parameters:
      volume: 5.0 m³
      temperature: 350 °C
      pressure: 25 barg
      k0: 1.2e6 1/s
      Ea: 85000 J/mol
      delta_H: -120000 J/mol
    instruments:
      - TIC-201: {range: [200, 400], units: °C, Kp: 2.5, Ti: 120}
      - PIC-201: {range: [10, 40], units: barg}
    connections:
      - to: E-101
        type: mass_coupling
        flow: 100 kg/h
        
  - tag: E-101
    model: HX_CounterCurrent
    parameters:
      UA: 5000 W/K
      F_hot: 100 kg/h
      F_cold: 200 kg/h
    connections:
      - to: V-401
        type: mass_coupling

matrix:
  size: 7
  blocks:
    - row: [0,2]
      col: [0,2]
      unit: R-301
      model: CSTR
    - row: [3,4]
      col: [3,4]
      unit: E-101
      model: HX
    - row: [0,2]
      col: [3,4]
      coupling: mass_flow
      from: R-301
      to: E-101
```

## UI: Configuration Builder Panel

In PlantSketch editor, add a "Configure" tab (next to Ask/Describe):

```
┌─────────────────────────────────────────────┐
│ CONFIGURE FOR SIMULATION                     │
│                                              │
│ Model Assignment              [Auto-assign]  │
│ ┌──────────────────────────────────────────┐ │
│ │ R-301  │ CSTR           │ ✓ 3/10 params │ │
│ │ E-101  │ HX_Counter     │ ✗ 0/6 params  │ │
│ │ V-401  │ Flash          │ ✗ 0/8 params  │ │
│ │ P-101  │ Pump           │ ✗ 0/4 params  │ │
│ └──────────────────────────────────────────┘ │
│                                              │
│ Parameter Completeness: 15%                  │
│ ████░░░░░░░░░░░░░░░░░░░░░░                  │
│                                              │
│ [Import Datasheet]  [Estimate with Claude]   │
│                                              │
│ Selected: R-301 (CSTR)                       │
│ ┌──────────────────────────────────────────┐ │
│ │ Volume:     [5.0    ] m³    ← datasheet │ │
│ │ Temperature:[350    ] °C    ← datasheet │ │
│ │ Pressure:   [25     ] barg  ← datasheet │ │
│ │ k₀:         [1.2e6  ] 1/s  ← estimated │ │
│ │ Ea:         [85000  ] J/mol ← estimated │ │
│ │ ΔH_rxn:     [       ] J/mol             │ │
│ │ ρ:          [       ] kg/m³             │ │
│ │ Cp:         [       ] J/kg/K            │ │
│ └──────────────────────────────────────────┘ │
│                                              │
│ [Build Matrix]  [Run enableSim]              │
└─────────────────────────────────────────────┘
```

## Workflow

1. PlantSketch extracts P&ID → espx with topology
2. User clicks "Configure" tab
3. Auto-assign models based on equipment kind
4. Import datasheet CSV OR type parameters in Describe
5. Claude estimates missing parameters from Perry's
6. "Build Matrix" generates enhanced YMPL
7. "Run enableSim" calls `enable validate` + `enable build`
8. Results (eigenvalues, HAZOP) display in PlantSketch
9. Alarm setpoints flow back to ENGRAM via VIDS update

## Data Flow Back

enableSim results feed BACK to PlantSketch:

```
enableSim output              PlantSketch receives
─────────────                 ────────────────────
λ₁ = +0.078 (unstable)   →   Flag R-301 as unstable
rank(B) = 2               →   Highlight TIC-201, LIC-201 as critical
HAZOP: HIGH_TEMP critical →   Set alarm setpoints on TIC-201
Startup sequence           →   Controller commissioning order
```

This completes the circle:
Paper P&ID → PlantSketch → enableSim → alarm setpoints → ENGRAM → enVIEW

// Canonical ISA-5.1 symbol classification — moved out of ISANodes.tsx (which
// re-exports these unchanged) so the rendering component file only contains
// components, and this pure logic is importable by non-component code
// (processLayout.ts, DrawPalette.tsx) without pulling in React types.
//
// This is the ONE canonical `getNodeType`/`isValveTag`/color-mapping
// implementation. It is NOT the same thing as CanvasScreen's `isInstrument`/
// `isOffPage` (domain/isa/instrument.ts) — those answer a narrower yes/no
// question ("is this conceptually an instrument for soft-tag grouping?") from
// a raw kind string, while `getNodeType` here maps a kind+label pair to one
// of ~28 specific render-shape names. Different purpose, deliberately kept
// separate per Phase 6's guidance not to merge semantically different logic.

// Theme.valve / Theme.offPage inlined below (not imported from
// components/canvas/theme.ts) so this domain module has zero UI-layer
// dependency; theme.ts itself is still the source of truth for rendering.

// Kind → tag-prefix defaults for CanvasScreen's draw-mode tag input modal.
export const TAG_PREFIXES: Record<string, string> = {
  // Vessels
  vessel: 'V-', vessel_v: 'V-', vessel_h: 'V-', separator: 'D-',
  flash_drum: 'D-', knockout: 'KO-', accumulator: 'D-', surge_drum: 'D-',
  tank_atm: 'T-', tank_cone: 'T-', hopper: 'BN-',
  sphere_vessel: 'V-', horton_sphere: 'TK-', bullet_tank: 'TK-',
  tank_cone_roof: 'T-', tank_dome_roof: 'T-', tank_floating_roof: 'T-', tank_ifr: 'T-',
  cryo_tank: 'T-', double_wall_tank: 'T-',
  // Columns
  column: 'C-', dist_tray: 'C-', dist_packed: 'C-',
  absorber: 'C-', scrubber: 'C-', stripper: 'C-', adsorption: 'C-',
  dist_column: 'C-', fractionator: 'C-', deethanizer: 'C-',
  debutanizer: 'C-', stabilizer_column: 'C-', vacuum_tower: 'C-', reactor_column: 'R-',
  // Reactors
  reactor: 'R-', cstr: 'R-', pfr: 'R-', batch_reactor: 'R-',
  fixed_bed: 'R-', fluidized_bed: 'R-',
  bubble_column_reactor: 'R-', loop_reactor: 'R-', slurry_reactor: 'R-',
  membrane_reactor: 'R-', trickle_bed_reactor: 'R-', catalytic_cracker: 'R-', furnace_reactor: 'R-',
  // Heat exchangers
  heat_exchanger: 'E-', hx_st: 'E-', hx_plate: 'E-',
  condenser: 'E-', reboiler_k: 'E-', air_cooler: 'EC-',
  fired_heater: 'H-', boiler: 'H-',
  spiral_hx: 'E-', double_pipe_hx: 'E-', plate_frame_hx: 'E-', hairpin_hx: 'E-',
  evaporator: 'E-', economizer: 'E-', superheater: 'E-', waste_heat_boiler: 'H-',
  // Rotating
  pump: 'P-', pump_cent: 'P-', pump_pd: 'P-', mixer: 'M-',
  compressor: 'K-', comp_cent: 'K-', comp_recip: 'K-', blower: 'BL-',
  gear_pump: 'P-', screw_pump: 'P-', diaphragm_pump: 'P-', peristaltic_pump: 'P-',
  vacuum_pump: 'P-', turbine: 'KT-', steam_turbine: 'KT-', gas_turbine: 'KT-',
  electric_motor: 'MTR-', gearbox: 'GB-', centrifugal_blower: 'BL-', roots_blower: 'BL-',
  // Separation
  filter: 'S-', filter_pf: 'S-', cyclone: 'CY-',
  centrifuge: 'CF-', membrane: 'ME-',
  decanter: 'S-', clarifier: 'S-', three_phase_sep: 'D-', oil_water_sep: 'S-',
  esp: 'S-', demister: 'S-', coalescer: 'S-', settling_tank: 'T-',
  // Instruments
  transmitter: 'FT-', controller: 'FIC-', indicator: 'FI-',
  switch: 'FSH-', analyzer: 'AT-', element: 'FE-', recorder: 'FR-',
  ft: 'FT-', lt: 'LT-', pt: 'PT-', tt: 'TT-', at: 'AT-',
  fe: 'FE-', le: 'LE-', pe: 'PE-', te: 'TE-',
  fic: 'FIC-', fr: 'FR-', fsh: 'FSH-', fsl: 'FSL-',
  dcs: 'DCS-', plc: 'PLC-', sis: 'SIS-',
  // Valves
  control_valve: 'FV-', hand_valve: 'HV-', check_valve: 'XV-',
  relief_valve: 'PSV-', cv_globe: 'FV-', cv_ball: 'BV-',
  cv_butterfly: 'BFV-', cv_gate: 'GV-',
  checkvalve: 'XV-', psv: 'PSV-', rupture_disc: 'RD-',
  three_way_valve: 'TWV-', three_way_solenoid_valve: 'TWSV-',
  normally_closed_valve: 'NCV-', plug_valve: 'PLV-',
  pcv: 'PCV-', back_pressure_regulator: 'BPR-', actuated_valve_general: 'XV-',
  mfm: 'MFM-', td: 'TD-', ty: 'TY-', fy: 'FY-', oa: 'OA-', pic: 'PIC-',
  auto_man_selector: 'HS-',
  mixing_tube: 'MX-', micron_filter: 'MF-',
  on_page_connector: 'ONP-', continuation_arrow: 'CONT-',
  // Electrical
  motor: 'MOT-', hv_motor: 'MOT-', lv_motor: 'MOT-', vfd: 'VFD-', mcc: 'MCC-',
  generator: 'GEN-', diesel_generator: 'GEN-', transformer: 'XFMR-', ups: 'UPS-',
  battery_bank: 'BB-', switchboard: 'SWBD-', distribution_panel: 'DP-',
  junction_box: 'JB-', terminal_box: 'TB-', control_panel: 'CP-',
  local_control_station: 'LCS-', disconnect_switch: 'DS-', circuit_breaker: 'CB-',
  fuse: 'FU-', ground: 'GND-', lightning_protection: 'LPS-',
  cable_tray: 'CT-', cable_junction: 'CJ-', lighting_fixture: 'LT-', emergency_lighting: 'ELT-',
  // Utilities
  steam_trap: 'ST-', steam_separator: 'D-', steam_drum: 'D-', steam_header: 'STM-',
  utility_line: 'U-', utility_header: 'HDR-',
  // Fire & Safety
  fire_water_pump: 'FWP-', jockey_pump: 'JP-', diesel_fire_pump: 'DFP-',
  deluge_valve: 'DV-', fire_hydrant: 'FH-', sprinkler_head: 'SPK-',
  water_monitor: 'WM-', foam_monitor: 'FM-', smoke_detector: 'SD-',
  heat_detector: 'HD-', flame_detector: 'FLD-', gas_detector: 'GD-', toxic_gas_detector: 'TGD-',
  emergency_shower: 'ES-', eye_wash_station: 'EW-', safety_shower: 'SS-',
  escape_breathing_apparatus: 'EBA-', fire_extinguisher: 'FE-', fire_alarm: 'FA-',
  manual_call_point: 'MCP-', emergency_stop: 'ESTOP-', flame_arrestor: 'FLA-',
  explosion_vent: 'EV-', blast_relief_panel: 'BRP-', pressure_vent: 'PV-', emergency_vent: 'EMV-',
}

type ColorsT = { bg: string; border: string; text: string }

export function equipColors(kind: string): ColorsT {
  switch ((kind ?? '').toLowerCase()) {
    case 'heat_exchanger': case 'hx_st': case 'hx_plate':
    case 'condenser': case 'reboiler_k': case 'air_cooler':
    case 'fired_heater': case 'boiler':
    case 'spiral_hx': case 'double_pipe_hx': case 'plate_frame_hx': case 'hairpin_hx':
    case 'evaporator': case 'economizer': case 'superheater': case 'waste_heat_boiler':
      return { bg: '#152a1f', border: '#22c55e', text: '#86efac' }
    case 'reactor': case 'cstr': case 'pfr': case 'batch_reactor':
    case 'fixed_bed': case 'fluidized_bed':
      return { bg: '#2a1515', border: '#ef4444', text: '#fca5a5' }
    case 'compressor': case 'comp_cent': case 'comp_recip': case 'blower':
    case 'turbine': case 'steam_turbine': case 'gas_turbine':
    case 'centrifugal_blower': case 'roots_blower':
      return { bg: '#15182a', border: '#6366f1', text: '#a5b4fc' }
    case 'column': case 'absorber': case 'adsorption':
    case 'dist_tray': case 'dist_packed': case 'scrubber': case 'stripper':
      return { bg: '#20162e', border: '#a855f7', text: '#d8b4fe' }
    case 'pump': case 'pump_cent': case 'pump_pd': case 'mixer':
    case 'gear_pump': case 'screw_pump': case 'diaphragm_pump': case 'peristaltic_pump':
    case 'vacuum_pump': case 'electric_motor': case 'gearbox':
      return { bg: '#152215', border: '#4ade80', text: '#86efac' }
    case 'filter': case 'filter_pf': case 'cyclone':
    case 'centrifuge': case 'membrane':
    case 'decanter': case 'clarifier': case 'three_phase_sep': case 'oil_water_sep':
    case 'esp': case 'demister': case 'coalescer': case 'settling_tank':
      return { bg: '#1a1c2e', border: '#60a5fa', text: '#93c5fd' }
    case 'motor': case 'hv_motor': case 'lv_motor': case 'vfd': case 'mcc':
    case 'generator': case 'diesel_generator': case 'transformer': case 'ups':
    case 'battery_bank': case 'switchboard': case 'distribution_panel':
    case 'junction_box': case 'terminal_box': case 'control_panel':
    case 'local_control_station': case 'disconnect_switch': case 'circuit_breaker':
    case 'fuse': case 'ground': case 'lightning_protection':
    case 'cable_tray': case 'cable_junction': case 'lighting_fixture': case 'emergency_lighting':
      return { bg: '#2a2007', border: '#f59e0b', text: '#fcd34d' }
    case 'steam_trap': case 'steam_separator': case 'steam_drum': case 'steam_header':
    case 'utility_line': case 'utility_header':
      return { bg: '#0c2432', border: '#38bdf8', text: '#7dd3fc' }
    case 'fire_water_pump': case 'jockey_pump': case 'diesel_fire_pump':
    case 'deluge_valve': case 'fire_hydrant': case 'sprinkler_head':
    case 'water_monitor': case 'foam_monitor': case 'smoke_detector':
    case 'heat_detector': case 'flame_detector': case 'gas_detector': case 'toxic_gas_detector':
    case 'emergency_shower': case 'eye_wash_station': case 'safety_shower':
    case 'escape_breathing_apparatus': case 'fire_extinguisher': case 'fire_alarm':
    case 'manual_call_point': case 'emergency_stop': case 'flame_arrestor':
    case 'explosion_vent': case 'blast_relief_panel': case 'pressure_vent': case 'emergency_vent':
      return { bg: '#2a1212', border: '#dc2626', text: '#fca5a5' }
    case 'connector':
      return { bg: '#111620', border: '#64748b', text: '#94a3b8' }
    default:
      return { bg: '#152232', border: '#3b82f6', text: '#93c5fd' }
  }
}

const LETTER_COLORS: Record<string, ColorsT> = {
  F: { bg: '#0c2030', border: '#0ea5e9', text: '#7dd3fc' },
  P: { bg: '#1c0e30', border: '#a855f7', text: '#d8b4fe' },
  T: { bg: '#2a0f0f', border: '#ef4444', text: '#fca5a5' },
  L: { bg: '#0d2016', border: '#22c55e', text: '#86efac' },
  A: { bg: '#201c00', border: '#eab308', text: '#fef08a' },
  S: { bg: '#1c1400', border: '#d97706', text: '#fcd34d' },
}

export const VALVE_C: ColorsT = { bg: '#1a1c20', border: '#F4B23A', text: '#94a3b8' }
export const OFFPAGE_C: ColorsT = { bg: '#111620', border: '#64748B', text: '#64748b' }

export const VALVE_RE = /^(CV|HV|XV|FV|PV|LV|TV|SV|SDV|BDV|ESD|ESDV|PSV|PRV|RV|ORV|ADV|PCV)\d*[-_]/i
export const isValveTag = (lbl: string) => VALVE_RE.test(lbl)

function isaLetter(lbl: string): string {
  const m = lbl.match(/^([A-Z]+)/i)
  return m ? m[1][0].toUpperCase() : '?'
}

export function instrColors(lbl: string): ColorsT {
  if (isValveTag(lbl)) return VALVE_C
  return LETTER_COLORS[isaLetter(lbl)] ?? { bg: '#1e1d13', border: '#f59e0b', text: '#fef3c7' }
}

// Equipment tag display convention — "P101" -> "P-101". Leaves tags that
// already carry a separator (P-101, P_101) alone.
export function formatTag(lbl: string): string {
  if (/[-_]/.test(lbl)) return lbl.replace(/_/g, '-')
  const m = lbl.match(/^([A-Za-z]+)(\d+.*)$/)
  return m ? `${m[1]}-${m[2]}` : lbl
}

// SVG <text> neither wraps nor shrinks, so a label wider than its viewBox is
// clipped at BOTH edges — a long equipment name rendered as "VABLE AQUEOUS
// SAMPL" instead of "AVAILABLE AQUEOUS SAMPLE". Returns the <text> props that
// keep `shown` inside `maxWidth`: a smaller font first, then SVG's native
// textLength squeeze once the legibility floor is hit. Text that already fits
// is returned untouched, so short ISA tags render exactly as before.
// ponytail: single-line squeeze — if long vessel names still read poorly on the
// narrow (60-wide) symbols, upgrade this to a two-line <tspan> wrap.
const AVG_GLYPH_EM = 0.58   // bold sans average; avoids a getComputedTextLength() measure pass
const MIN_FONT_PX  = 7

export function fitTag(shown: string, maxWidth: number, fontSize: number): {
  fontSize: number; textLength?: number; lengthAdjust?: 'spacingAndGlyphs'
} {
  const chars = shown.length
  if (!chars || chars * fontSize * AVG_GLYPH_EM <= maxWidth) return { fontSize }
  const scaled = Math.max(MIN_FONT_PX, Math.floor(maxWidth / (chars * AVG_GLYPH_EM)))
  if (chars * scaled * AVG_GLYPH_EM <= maxWidth) return { fontSize: scaled }
  return { fontSize: scaled, textLength: maxWidth, lengthAdjust: 'spacingAndGlyphs' }
}

// ── Node type mapping ─────────────────────────────────────────────────────────
export function getNodeType(kind: string, label: string, offPage: boolean): string {
  if (offPage) return 'offpage'
  if ((kind ?? '').toLowerCase() === 'junction') return 'junction'
  // Accept both ISA kind names (lowercase, e.g. "valve") and YOLO PascalCase type
  // names (e.g. "Ball_Valve") — normalise to lowercase for all checks below.
  const k = (kind ?? '').toLowerCase()
  const l = (label ?? '').toLowerCase()

  // Helper to check if a string matches a valve type
  const isType = (str: string, types: string[]) => types.some(t => str.includes(t))

  // Exact-kind valve variants — must run before the fragment-matching valve
  // checks below, since e.g. k.includes('solenoid_valve') or
  // k.includes('pcv') would otherwise catch these first and collapse them
  // into the generic solenoid/regulator/actuated shape.
  if (k === 'three_way_valve') return 'three_way_valve'
  if (k === 'three_way_solenoid_valve') return 'three_way_solenoid_valve'
  if (k === 'normally_closed_valve') return 'normally_closed_valve'
  if (k === 'plug_valve') return 'plug_valve'
  if (k === 'pcv') return 'pcv'
  if (k === 'back_pressure_regulator') return 'back_pressure_regulator'
  if (k === 'actuated_valve_general') return 'actuated_valve_general'

  // Valve kinds — check both kind and label
  if (isType(k, ['cv_ball', 'ball_valve']) || isType(l, ['ball_valve'])) return 'ball_valve'
  if (isType(k, ['cv_butterfly', 'butterfly_valve']) || isType(l, ['butterfly_valve'])) return 'butterfly_valve'
  if (isType(k, ['cv_gate', 'gate_valve']) || isType(l, ['gate_valve'])) return 'gate_valve'

  if (isType(k, ['hand_valve', 'manual_valve', 'blowdown_valve']) ||
    isType(l, ['hand_valve', 'manual_valve', 'blowdown_valve', '2_way_valve', '3_way_valve'])) return 'hand_valve'

  if (isType(k, ['check_valve', 'checkvalve', 'nrv']) || isType(l, ['check_valve', 'checkvalve', 'nrv', 'cv .'])) return 'check_valve'

  if (isType(k, ['rupture_disc']) || isType(l, ['rupture_disc'])) return 'rupture_disc'

  if (isType(k, ['relief_valve', 'relief', 'psv', 'prv', 'safety_valve', 'pressure_safety', 'safety_device']) || isType(l, ['relief_valve', 'psv', 'prv', 'safety_valve'])) return 'relief_valve'

  if (isType(k, ['orifice_plate', 'orifice', 'restriction_orifice', 'restrictor', 'flow_restrictor']) || isType(l, ['orifice'])) return 'orifice'

  if (isType(k, ['needle_valve']) || isType(l, ['needle_valve'])) return 'needle_valve'

  if (isType(k, ['solenoid_valve']) || isType(l, ['solenoid_valve', 'solenoid'])) return 'solenoid_valve'

  if (isType(k, ['regulator', 'pressure_regulator', 'pcrv', 'pcv']) || isType(l, ['regulator', 'bpr'])) return 'regulator'

  // Generic / actuated / shutdown valves and bare actuators → control-valve symbol
  if (isType(k, ['control_valve', 'valve', 'cv_globe', 'actuated', 'actuator', 'emergency_shutdown', 'esd'])) return 'valve'

  if (isValveTag(label)) return 'valve'

  // Instrument kinds — differentiate bubble shapes
  if (k === 'level_glass') return 'level_glass'
  // Exact-kind Control & Safety palette items get their own dedicated symbol,
  // ahead of the generic instrument/dcs_func/sis_func fallbacks below (which
  // otherwise collapse fic/fr/fsh/fsl into one identical circle, and dcs/plc
  // into one identical square, and sis into the generic safety diamond).
  if (k === 'dcs') return 'ctrl_dcs'
  if (k === 'plc') return 'ctrl_plc'
  if (k === 'sis') return 'ctrl_sis'
  if (k === 'fic') return 'ctrl_controller'
  if (k === 'fr') return 'ctrl_recorder'
  if (k === 'fsh') return 'ctrl_high_switch'
  if (k === 'fsl') return 'ctrl_low_switch'
  if (['computer_function', 'hmi', 'dcs_func'].includes(k)) return 'dcs_func'
  if (['switch', 'safety_func'].includes(k)) return 'sis_func'
  // Exact ISA kind names
  if (k === 'quick_connect') return 'quick_connect'
  if (k === 'thermocouple') return 'thermocouple'
  // New bubble/device instrument variants — exact match, ahead of the
  // generic instrument list below (which already claims bare 'fy').
  if (k === 'mfm') return 'mfm'
  if (k === 'td') return 'td'
  if (k === 'ty' || k === 'fy') return 'transducer'
  if (k === 'oa') return 'alarm'
  if (k === 'pic') return 'ctrl_controller'
  if (k === 'auto_man_selector') return 'auto_man_selector'

  if (['transmitter', 'controller', 'indicator', 'recorder', 'analyzer', 'element', 'instrument',
    'ft', 'lt', 'pt', 'tt', 'at', 'fe', 'le', 'pe', 'te',
    'fic', 'fi', 'fr', 'fsh', 'fsl', 'fy', 'totalizer', 'converter', 'alarm',
    'meter', 'gauge', 'sensor', 'flow_meter'].includes(k)) return 'instrument'
  // YOLO compound instrument type names (e.g. "pressure_indicator", "temperature_element",
  // "mass_flow_meter", "differential_temperature", "control_device", "pid_control") —
  // match by fragment. Valves/equipment are already resolved above, so these
  // fragments only catch remaining instrument & control-function classes.
  if (['indicator', 'element', 'controller', 'transmitter', 'meter', 'gauge',
    'sensor', 'recorder', 'analyzer', 'totalizer', 'indicating', 'control',
    'differential', 'transducer', 'thermocouple', 'relay', 'selector',
    'interlock', 'sampling', 'quantity', 'detector', 'monitor'].some(f => k.includes(f))) return 'instrument'

  switch (k) {
    case 'pump': case 'pump_cent': return 'pump_cent'
    case 'pump_pd': return 'pump_pd'
    case 'mixer': return 'mixer'
    case 'compressor': case 'comp_cent': case 'expander': return 'comp_cent'
    case 'comp_recip': return 'comp_recip'
    case 'blower': return 'blower'
    case 'gear_pump': return 'gear_pump'
    case 'screw_pump': return 'screw_pump'
    case 'diaphragm_pump': return 'diaphragm_pump'
    case 'peristaltic_pump': return 'peristaltic_pump'
    case 'vacuum_pump': return 'vacuum_pump'
    case 'turbine': return 'turbine'
    case 'steam_turbine': return 'steam_turbine'
    case 'gas_turbine': return 'gas_turbine'
    case 'electric_motor': return 'electric_motor'
    case 'gearbox': return 'gearbox'
    case 'centrifugal_blower': return 'centrifugal_blower'
    case 'roots_blower': return 'roots_blower'
    case 'heat_exchanger': case 'hx_st': case 'heater': return 'hx_shell_tube'
    case 'hx_plate': return 'hx_plate'
    case 'condenser': return 'hx_condenser'
    case 'reboiler_k': return 'hx_reboiler'
    case 'air_cooler': return 'hx_air_cooler'
    case 'fired_heater': return 'hx_fired_heater'
    case 'boiler': return 'hx_boiler'
    case 'spiral_hx': return 'spiral_hx'
    case 'double_pipe_hx': return 'double_pipe_hx'
    case 'plate_frame_hx': return 'plate_frame_hx'
    case 'hairpin_hx': return 'hairpin_hx'
    case 'evaporator': return 'evaporator'
    case 'economizer': return 'economizer'
    case 'superheater': return 'superheater'
    case 'waste_heat_boiler': return 'waste_heat_boiler'
    case 'vessel_vertical': case 'vessel_v': return 'vessel_v'
    // Atmospheric storage tanks — flat-bottomed cylinder, distinct from a pressure vessel
    case 'tank': case 'storage': case 'tank_atm': case 'tank_cone': return 'tank'
    case 'hopper': return 'hopper'
    case 'flash_drum': return 'flash_drum'
    case 'knockout': return 'knockout'
    case 'accumulator': case 'surge_drum': return 'accumulator'
    case 'sphere_vessel': return 'sphere_vessel'
    case 'horton_sphere': return 'horton_sphere'
    case 'bullet_tank': return 'bullet_tank'
    case 'tank_cone_roof': return 'tank_cone_roof'
    case 'tank_dome_roof': return 'tank_dome_roof'
    case 'tank_floating_roof': return 'tank_floating_roof'
    case 'tank_ifr': return 'tank_ifr'
    case 'cryo_tank': return 'cryo_tank'
    case 'double_wall_tank': return 'double_wall_tank'
    case 'vessel': case 'vessel_horizontal': case 'vessel_h': case 'separator': case 'separation_unit':
    case 'drum': return 'vessel_h'
    case 'reactor': case 'cstr': return 'cstr'
    case 'pfr': return 'pfr'
    case 'fixed_bed': return 'fixed_bed'
    case 'fluidized_bed': return 'fluidized_bed'
    case 'batch_reactor': return 'batch_reactor'
    case 'bubble_column_reactor': return 'bubble_column_reactor'
    case 'loop_reactor': return 'loop_reactor'
    case 'slurry_reactor': return 'slurry_reactor'
    case 'membrane_reactor': return 'membrane_reactor'
    case 'trickle_bed_reactor': return 'trickle_bed_reactor'
    case 'catalytic_cracker': return 'catalytic_cracker'
    case 'furnace_reactor': return 'furnace_reactor'
    case 'ejector': case 'jet_ejector': case 'venturi': return 'ejector'
    case 'filter': case 'filter_pf': return 'filter'
    case 'cyclone': return 'cyclone'
    case 'centrifuge': return 'centrifuge'
    case 'membrane': return 'membrane'
    case 'decanter': return 'decanter'
    case 'clarifier': return 'clarifier'
    case 'three_phase_sep': return 'three_phase_sep'
    case 'oil_water_sep': return 'oil_water_sep'
    case 'esp': return 'esp'
    case 'demister': return 'demister'
    case 'coalescer': return 'coalescer'
    case 'settling_tank': return 'settling_tank'
    case 'column': case 'dist_tray': case 'dist_column': case 'fractionator':
    case 'deethanizer': case 'debutanizer': case 'stabilizer_column': return 'tray_column'
    case 'dist_packed': return 'packed_column'
    case 'absorber': case 'adsorption': return 'absorber'
    case 'scrubber': return 'scrubber'
    case 'stripper': return 'stripper'
    case 'vacuum_tower': return 'vacuum_tower'
    case 'reactor_column': return 'reactor_column'
    // Electrical
    case 'motor': return 'motor'
    case 'hv_motor': return 'hv_motor'
    case 'lv_motor': return 'lv_motor'
    case 'vfd': return 'vfd'
    case 'mcc': return 'mcc'
    case 'generator': return 'generator'
    case 'diesel_generator': return 'diesel_generator'
    case 'transformer': return 'transformer'
    case 'ups': return 'ups'
    case 'battery_bank': return 'battery_bank'
    case 'switchboard': return 'switchboard'
    case 'distribution_panel': return 'distribution_panel'
    case 'junction_box': return 'junction_box'
    case 'terminal_box': return 'terminal_box'
    case 'control_panel': return 'control_panel'
    case 'local_control_station': return 'local_control_station'
    case 'disconnect_switch': return 'disconnect_switch'
    case 'circuit_breaker': return 'circuit_breaker'
    case 'fuse': return 'fuse'
    case 'ground': return 'ground'
    case 'lightning_protection': return 'lightning_protection'
    case 'cable_tray': return 'cable_tray'
    case 'cable_junction': return 'cable_junction'
    case 'lighting_fixture': return 'lighting_fixture'
    case 'emergency_lighting': return 'emergency_lighting'
    // Utilities — real equipment gets its own type; every service-line kind
    // (cooling water, nitrogen, caustic, etc.) collapses to the single
    // generic 'utility_line' shape, and header kinds to 'utility_header',
    // per ISA/ISO convention that services differ by tag, not by shape.
    case 'steam_trap': return 'steam_trap'
    case 'steam_separator': return 'steam_separator'
    case 'steam_drum': return 'steam_drum'
    case 'steam_header': return 'steam_header'
    case 'util_header_main': case 'util_header_branch': case 'util_header_dist': return 'utility_header'
    case 'util_cw': case 'util_chw': case 'util_bfw': case 'util_cr': case 'util_hw':
    case 'util_ng': case 'util_fg': case 'util_ia': case 'util_pa': case 'util_n2':
    case 'util_o2': case 'util_h2': case 'util_ca': case 'util_vac':
    case 'util_caustic': case 'util_acid': case 'util_dmw': case 'util_pw': case 'util_potable':
      return 'utility_line'
    // Fire & Safety
    case 'fire_water_pump': return 'fire_water_pump'
    case 'jockey_pump': return 'jockey_pump'
    case 'diesel_fire_pump': return 'diesel_fire_pump'
    case 'deluge_valve': return 'deluge_valve'
    case 'fire_hydrant': return 'fire_hydrant'
    case 'sprinkler_head': return 'sprinkler_head'
    case 'water_monitor': return 'water_monitor'
    case 'foam_monitor': return 'foam_monitor'
    case 'smoke_detector': return 'smoke_detector'
    case 'heat_detector': return 'heat_detector'
    case 'flame_detector': return 'flame_detector'
    case 'gas_detector': return 'gas_detector'
    case 'toxic_gas_detector': return 'toxic_gas_detector'
    case 'emergency_shower': return 'emergency_shower'
    case 'eye_wash_station': return 'eye_wash_station'
    case 'safety_shower': return 'safety_shower'
    case 'escape_breathing_apparatus': return 'escape_breathing_apparatus'
    case 'fire_extinguisher': return 'fire_extinguisher'
    case 'fire_alarm': return 'fire_alarm'
    case 'manual_call_point': return 'manual_call_point'
    case 'emergency_stop': return 'emergency_stop'
    case 'flame_arrestor': return 'flame_arrestor'
    case 'explosion_vent': return 'explosion_vent'
    case 'blast_relief_panel': return 'blast_relief_panel'
    case 'pressure_vent': return 'pressure_vent'
    case 'emergency_vent': return 'emergency_vent'
    case 'mixing_tube': return 'mixing_tube'
    case 'micron_filter': return 'micron_filter'
    case 'on_page_connector': return 'on_page_connector'
    case 'continuation_arrow': return 'continuation_arrow'
    case 'vendor_package': case 'package': return 'vendor_package'
    default: return 'equipment'
  }
}

// ── Node sizing ───────────────────────────────────────────────────────────────
// Kept at their existing (small) size — these sit inline on a pipe/signal
// line, so enlarging them would break pipe-routing spacing and the
// bowtie/circle-on-line drafting convention.
const PIPE_SCALE_EXEMPT = new Set([
  'junction', 'quick_connect', 'thermocouple', 'instrument', 'dcs_func', 'sis_func',
  'ctrl_controller', 'ctrl_recorder', 'ctrl_high_switch', 'ctrl_low_switch',
  'ctrl_dcs', 'ctrl_plc', 'ctrl_sis', 'level_glass',
  'ball_valve', 'butterfly_valve', 'gate_valve', 'rupture_disc', 'valve', 'regulator',
  'hand_valve', 'check_valve', 'relief_valve', 'orifice', 'needle_valve', 'solenoid_valve',
  'offpage', 'disconnect_switch', 'circuit_breaker', 'fuse', 'ground', 'lightning_protection',
  'cable_junction', 'junction_box', 'terminal_box', 'deluge_valve',
  'manual_call_point', 'emergency_stop', 'steam_trap', 'utility_line',
  'three_way_valve', 'three_way_solenoid_valve', 'normally_closed_valve', 'plug_valve',
  'pcv', 'back_pressure_regulator', 'actuated_valve_general',
  'mfm', 'td', 'transducer', 'alarm', 'auto_man_selector',
  'on_page_connector', 'continuation_arrow',
])
// Everything else is a placed piece of equipment — scale it up a bit so it
// reads clearly against connecting pipes on the canvas.
const EQUIPMENT_SCALE = 2

export function getNodeSize(type: string, softCount = 0): { w: number; h: number } {
  const { w, h } = rawNodeSize(type, softCount)
  if (PIPE_SCALE_EXEMPT.has(type)) return { w, h }
  return { w: Math.round(w * EQUIPMENT_SCALE), h: Math.round(h * EQUIPMENT_SCALE) }
}

function rawNodeSize(type: string, softCount = 0): { w: number; h: number } {
  switch (type) {
    case 'junction': return { w: 16, h: 16 }  // 16px hit body; dot drawn small + centered
    case 'quick_connect': return { w: 32, h: 24 }
    case 'thermocouple': return { w: 44, h: 44 }
    case 'instrument': return softCount > 0 ? { w: 52, h: 64 } : { w: 52, h: 52 }
    case 'dcs_func': return { w: 52, h: 52 }
    case 'sis_func': return { w: 52, h: 52 }
    case 'ctrl_controller': case 'ctrl_recorder':
    case 'ctrl_high_switch': case 'ctrl_low_switch': return { w: 52, h: 52 }
    case 'ctrl_dcs': case 'ctrl_plc': case 'ctrl_sis': return { w: 64, h: 64 }
    case 'level_glass': return { w: 22, h: 52 }
    case 'ball_valve': case 'butterfly_valve': return { w: 54, h: 50 }
    case 'gate_valve': return { w: 54, h: 56 }
    case 'rupture_disc': return { w: 50, h: 30 }
    case 'valve': return { w: 54, h: 50 }
    case 'regulator': return { w: 54, h: 50 }
    case 'hand_valve': return { w: 46, h: 36 }
    case 'check_valve': return { w: 46, h: 36 }
    case 'relief_valve': return { w: 54, h: 46 }
    case 'orifice': return { w: 40, h: 36 }
    case 'needle_valve': return { w: 44, h: 36 }
    case 'solenoid_valve': return { w: 54, h: 44 }
    case 'ejector': return { w: 76, h: 52 }
    case 'pump_cent': case 'pump_pd': return { w: 62, h: 62 }
    case 'mixer': return { w: 64, h: 64 }
    case 'comp_cent': case 'comp_recip': case 'blower': return { w: 70, h: 70 }
    case 'gear_pump': case 'diaphragm_pump': case 'peristaltic_pump': return { w: 62, h: 62 }
    case 'screw_pump': return { w: 76, h: 50 }
    case 'vacuum_pump': return { w: 76, h: 56 }
    case 'turbine': case 'steam_turbine': case 'gas_turbine': return { w: 90, h: 64 }
    case 'electric_motor': return { w: 76, h: 56 }
    case 'gearbox': return { w: 76, h: 56 }
    case 'centrifugal_blower': return { w: 76, h: 76 }
    case 'roots_blower': return { w: 76, h: 56 }
    case 'hx_shell_tube': return { w: 96, h: 64 }
    case 'hx_plate': return { w: 76, h: 76 }
    case 'hx_condenser': case 'hx_reboiler': return { w: 76, h: 76 }
    case 'hx_air_cooler': return { w: 96, h: 60 }
    case 'hx_fired_heater': return { w: 76, h: 92 }
    case 'hx_boiler': return { w: 76, h: 106 }
    case 'spiral_hx': return { w: 76, h: 76 }
    case 'double_pipe_hx': return { w: 76, h: 50 }
    case 'plate_frame_hx': return { w: 76, h: 76 }
    case 'hairpin_hx': return { w: 76, h: 76 }
    case 'evaporator': case 'economizer': return { w: 76, h: 92 }
    case 'superheater': return { w: 76, h: 76 }
    case 'waste_heat_boiler': return { w: 76, h: 76 }
    case 'vessel_h': return { w: 88, h: 60 }
    case 'vessel_v': return { w: 76, h: 126 }
    case 'flash_drum': return { w: 76, h: 126 }
    case 'knockout': return { w: 130, h: 88 }
    case 'accumulator': return { w: 76, h: 126 }
    case 'tank': return { w: 58, h: 70 }
    case 'hopper': return { w: 78, h: 106 }
    case 'sphere_vessel': return { w: 96, h: 96 }
    case 'horton_sphere': return { w: 96, h: 110 }
    case 'bullet_tank': return { w: 130, h: 88 }
    case 'tank_cone_roof': case 'tank_dome_roof':
    case 'tank_floating_roof': case 'tank_ifr': return { w: 58, h: 70 }
    case 'cryo_tank': case 'double_wall_tank': return { w: 58, h: 70 }
    case 'cstr': case 'batch_reactor': case 'fixed_bed': case 'fluidized_bed': return { w: 94, h: 126 }
    case 'pfr': return { w: 130, h: 88 }
    case 'bubble_column_reactor': case 'slurry_reactor':
    case 'membrane_reactor': case 'trickle_bed_reactor': return { w: 94, h: 126 }
    case 'loop_reactor': return { w: 110, h: 80 }
    case 'catalytic_cracker': return { w: 90, h: 110 }
    case 'furnace_reactor': return { w: 76, h: 92 }
    case 'filter': return { w: 70, h: 52 }
    case 'cyclone': return { w: 64, h: 64 }
    case 'centrifuge': return { w: 68, h: 60 }
    case 'membrane': return { w: 70, h: 52 }
    case 'decanter': case 'three_phase_sep': case 'oil_water_sep': return { w: 90, h: 60 }
    case 'clarifier': case 'esp': case 'settling_tank': return { w: 76, h: 76 }
    case 'demister': case 'coalescer': return { w: 70, h: 76 }
    case 'tray_column': case 'packed_column': case 'absorber':
    case 'scrubber': case 'stripper': return { w: 62, h: 152 }
    case 'vacuum_tower': case 'reactor_column': return { w: 62, h: 152 }
    // Electrical
    case 'motor': case 'hv_motor': case 'lv_motor': return { w: 64, h: 64 }
    case 'vfd': case 'mcc': case 'switchboard': return { w: 64, h: 64 }
    case 'generator': case 'diesel_generator': return { w: 64, h: 70 }
    case 'transformer': return { w: 64, h: 64 }
    case 'ups': case 'control_panel': case 'local_control_station': return { w: 64, h: 64 }
    case 'battery_bank': return { w: 60, h: 56 }
    case 'distribution_panel': return { w: 64, h: 64 }
    case 'junction_box': case 'terminal_box': return { w: 60, h: 56 }
    case 'disconnect_switch': case 'circuit_breaker': case 'fuse': return { w: 44, h: 64 }
    case 'ground': case 'lightning_protection': return { w: 56, h: 60 }
    case 'cable_tray': return { w: 64, h: 40 }
    case 'cable_junction': return { w: 64, h: 56 }
    case 'lighting_fixture': case 'emergency_lighting': return { w: 64, h: 64 }
    // Utilities
    case 'steam_trap': return { w: 60, h: 40 }
    case 'steam_separator': return { w: 60, h: 66 }
    case 'steam_drum': return { w: 90, h: 60 }
    case 'steam_header': case 'utility_header': return { w: 64, h: 48 }
    case 'utility_line': return { w: 64, h: 40 }
    // Fire & Safety
    case 'fire_water_pump': case 'diesel_fire_pump': return { w: 62, h: 62 }
    case 'jockey_pump': return { w: 62, h: 62 }
    case 'deluge_valve': return { w: 64, h: 56 }
    case 'fire_hydrant': return { w: 64, h: 56 }
    case 'sprinkler_head': return { w: 64, h: 64 }
    case 'water_monitor': case 'foam_monitor': return { w: 64, h: 64 }
    case 'smoke_detector': case 'heat_detector': return { w: 60, h: 48 }
    case 'flame_detector': case 'gas_detector': case 'toxic_gas_detector': return { w: 60, h: 56 }
    case 'emergency_shower': case 'safety_shower': return { w: 64, h: 64 }
    case 'eye_wash_station': return { w: 64, h: 64 }
    case 'escape_breathing_apparatus': case 'fire_extinguisher': return { w: 60, h: 60 }
    case 'fire_alarm': return { w: 60, h: 60 }
    case 'manual_call_point': case 'emergency_stop': return { w: 60, h: 60 }
    case 'flame_arrestor': return { w: 64, h: 56 }
    case 'explosion_vent': case 'blast_relief_panel': return { w: 64, h: 64 }
    case 'pressure_vent': case 'emergency_vent': return { w: 60, h: 64 }
    // New valve variants
    case 'three_way_valve': case 'three_way_solenoid_valve': return { w: 54, h: 56 }
    case 'normally_closed_valve': return { w: 54, h: 50 }
    case 'plug_valve': return { w: 54, h: 50 }
    case 'pcv': case 'back_pressure_regulator': return { w: 54, h: 50 }
    case 'actuated_valve_general': return { w: 54, h: 50 }
    // New instrument bubbles/devices
    case 'mfm': case 'td': return { w: 52, h: 52 }
    case 'transducer': return { w: 52, h: 64 }
    case 'alarm': return { w: 52, h: 52 }
    case 'auto_man_selector': return { w: 64, h: 52 }
    // New equipment
    case 'mixing_tube': return { w: 70, h: 46 }
    case 'micron_filter': return { w: 60, h: 66 }
    // New connectors
    case 'on_page_connector': return { w: 52, h: 52 }
    case 'continuation_arrow': return { w: 56, h: 32 }
    case 'offpage': return { w: 108, h: 42 }
    case 'vendor_package': return { w: 400, h: 300 }
    case 'package': return { w: 260, h: 200 }
    default: return { w: 108, h: 56 }
  }
}

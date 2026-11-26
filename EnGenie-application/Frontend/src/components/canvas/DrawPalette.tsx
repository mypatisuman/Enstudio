import { useState } from 'react'
import type { ReactElement } from 'react'
import { equipColors, VALVE_C } from './ISANodes'
import {
  VerticalVessel, HorizontalVessel, FlashDrum, KnockoutDrum,
  Accumulator, AtmosphericTank, HopperSilo,
  SphericalVessel, HortonSphere, BulletTank, CryogenicTank, DoubleWallTank,
} from '../pid-symbols/vessels'
import {
  TrayColumn, PackedColumn, Absorber, Scrubber, Stripper,
  DistillationColumn, Fractionator, Deethanizer, Debutanizer, StabilizerColumn,
  VacuumTower, ReactorColumn,
} from '../pid-symbols/columns'
import {
  CSTR, PFR, FixedBed, FluidizedBed, BatchReactor,
  BubbleColumnReactor, LoopReactor, SlurryReactor, MembraneReactor,
  TrickleBedReactor, CatalyticCracker, FurnaceReactor,
} from '../pid-symbols/reactors'
import {
  ShellTube, PlateHeatExchanger, Condenser, Reboiler, AirCooler, FiredHeater, Boiler,
  SpiralHX, DoublePipeHX, PlateFrameHX, HairpinHX, Evaporator, Economizer, Superheater, WasteHeatBoiler,
} from '../pid-symbols/heat-exchangers'
import {
  CentrifugalPump, PDPump, CentrifugalCompressor, ReciprocatingCompressor, Blower, Mixer,
  GearPump, ScrewPump, DiaphragmPump, PeristalticPump, VacuumPump,
  Turbine, SteamTurbine, GasTurbine, ElectricMotor, Gearbox, CentrifugalBlower, RootsBlower,
} from '../pid-symbols/rotating'
import {
  Cyclone, Filter as FilterIcon, Centrifuge, Membrane,
  Decanter, Clarifier, ThreePhaseSeparator, OilWaterSeparator,
  ElectrostaticPrecipitator, Demister, Coalescer, SettlingTank,
} from '../pid-symbols/separation'
import {
  GlobeValve, BallValve, ButterflyValve, GateValve, CheckValve, PSV, RuptureDisc,
  ThreeWayValve, ThreeWaySolenoidValve, NormallyClosedValve, PlugValve,
  PressureRegulatorPCV, BackPressureRegulator, ActuatedValveGeneral,
} from '../pid-symbols/valves'
import {
  Controller, Recorder, HighSwitch, LowSwitch, DCS, PLC, SIS,
  MassFlowMeter, DifferentialTemperature, Transducer, Alarm, AutoManualSelector,
} from '../pid-symbols/control'
import { MixingTube, MicronFilter } from '../pid-symbols/equipment'
import { OnPageConnector, ContinuationArrow } from '../pid-symbols/connectors'
import {
  Motor, HighVoltageMotor, LowVoltageMotor, VFD, MCC, Generator, DieselGenerator,
  Transformer, UPS, BatteryBank, Switchboard, DistributionPanel, JunctionBox, TerminalBox,
  ControlPanel, LocalControlStation, DisconnectSwitch, CircuitBreaker, Fuse, Ground,
  LightningProtection, CableTray, CableJunction, LightingFixture, EmergencyLighting,
} from '../pid-symbols/electrical'
import {
  SteamTrap, SteamSeparator, SteamDrum, SteamHeader, UtilityLine, UtilityHeader,
} from '../pid-symbols/utilities'
import {
  FireWaterPump, JockeyPump, DieselFirePump, DelugeValve, FireHydrant, SprinklerHead,
  WaterMonitor, FoamMonitor, SmokeDetector, HeatDetector, FlameDetector, GasDetector, ToxicGasDetector,
  EmergencyShower, EyeWashStation, SafetyShower, EscapeBreathingApparatus, FireExtinguisher,
  FireAlarm, ManualCallPoint, EmergencyStop, FlameArrestor, ExplosionVent, BlastReliefPanel,
  PressureVent, EmergencyVent,
} from '../pid-symbols/fire-safety'

// ── Comprehensive palette item list ───────────────────────────────────────────

export interface PaletteItem { kind: string; label: string }

export const PALETTE_GROUPS: { title: string; items: PaletteItem[] }[] = [
  {
    title: 'Vessels & Tanks',
    items: [
      { kind: 'vessel_v',    label: 'Vessel (vert.)'  },
      { kind: 'vessel_h',    label: 'Vessel (horiz.)' },
      { kind: 'flash_drum',  label: 'Flash Drum'      },
      { kind: 'knockout',    label: 'Knockout Drum'   },
      { kind: 'accumulator', label: 'Accumulator'     },
      { kind: 'tank_atm',    label: 'Tank (atm.)'     },
      { kind: 'hopper',      label: 'Hopper / Silo'   },
      { kind: 'sphere_vessel',      label: 'Spherical Vessel' },
      { kind: 'horton_sphere',      label: 'Horton Sphere'    },
      { kind: 'bullet_tank',        label: 'Horizontal Storage (Bullet)' },
      { kind: 'tank_cone_roof',     label: 'Cone Roof Tank'   },
      { kind: 'tank_dome_roof',     label: 'Dome Roof Tank'   },
      { kind: 'tank_floating_roof', label: 'Floating Roof Tank' },
      { kind: 'tank_ifr',           label: 'Internal Floating Roof' },
      { kind: 'cryo_tank',          label: 'Cryogenic Tank'   },
      { kind: 'double_wall_tank',   label: 'Double Wall Tank' },
    ],
  },
  {
    title: 'Columns & Towers',
    items: [
      { kind: 'dist_tray',   label: 'Tray Column'   },
      { kind: 'dist_packed', label: 'Packed Column' },
      { kind: 'absorber',    label: 'Absorber'      },
      { kind: 'scrubber',    label: 'Scrubber'      },
      { kind: 'stripper',    label: 'Stripper'      },
      { kind: 'dist_column',       label: 'Distillation Column' },
      { kind: 'fractionator',      label: 'Fractionator'  },
      { kind: 'deethanizer',       label: 'Deethanizer'   },
      { kind: 'debutanizer',       label: 'Debutanizer'   },
      { kind: 'stabilizer_column', label: 'Stabilizer Column' },
      { kind: 'vacuum_tower',      label: 'Vacuum Tower'  },
      { kind: 'reactor_column',    label: 'Reactor Column' },
    ],
  },
  {
    title: 'Reactors',
    items: [
      { kind: 'cstr',          label: 'CSTR'         },
      { kind: 'pfr',           label: 'PFR (tubular)'},
      { kind: 'fixed_bed',     label: 'Fixed Bed'    },
      { kind: 'fluidized_bed', label: 'Fluidized Bed'},
      { kind: 'batch_reactor', label: 'Batch Reactor'},
      { kind: 'bubble_column_reactor', label: 'Bubble Column Reactor' },
      { kind: 'loop_reactor',          label: 'Loop Reactor'   },
      { kind: 'slurry_reactor',        label: 'Slurry Reactor' },
      { kind: 'membrane_reactor',      label: 'Membrane Reactor' },
      { kind: 'trickle_bed_reactor',   label: 'Trickle Bed Reactor' },
      { kind: 'catalytic_cracker',     label: 'Catalytic Cracker' },
      { kind: 'furnace_reactor',       label: 'Furnace Reactor' },
    ],
  },
  {
    title: 'Heat Exchangers',
    items: [
      { kind: 'hx_st',       label: 'Shell & Tube' },
      { kind: 'hx_plate',    label: 'Plate HX'     },
      { kind: 'condenser',   label: 'Condenser'    },
      { kind: 'reboiler_k',  label: 'Reboiler'     },
      { kind: 'air_cooler',  label: 'Air Cooler'   },
      { kind: 'fired_heater',label: 'Fired Heater' },
      { kind: 'boiler',      label: 'Boiler'       },
      { kind: 'spiral_hx',        label: 'Spiral HX'        },
      { kind: 'double_pipe_hx',   label: 'Double Pipe HX'   },
      { kind: 'plate_frame_hx',   label: 'Plate & Frame HX' },
      { kind: 'hairpin_hx',       label: 'Hairpin HX'       },
      { kind: 'evaporator',       label: 'Evaporator'       },
      { kind: 'economizer',       label: 'Economizer'       },
      { kind: 'superheater',      label: 'Superheater'      },
      { kind: 'waste_heat_boiler',label: 'Waste Heat Boiler'},
    ],
  },
  {
    title: 'Rotating Equipment',
    items: [
      { kind: 'pump_cent',  label: 'Centrifugal Pump' },
      { kind: 'pump_pd',    label: 'PD Pump'          },
      { kind: 'comp_cent',  label: 'Centrifugal Comp' },
      { kind: 'comp_recip', label: 'Recip. Comp.'     },
      { kind: 'blower',     label: 'Blower / Fan'     },
      { kind: 'mixer',      label: 'Mixer / Agitator' },
      { kind: 'gear_pump',          label: 'Gear Pump'         },
      { kind: 'screw_pump',         label: 'Screw Pump'        },
      { kind: 'diaphragm_pump',     label: 'Diaphragm Pump'    },
      { kind: 'peristaltic_pump',   label: 'Peristaltic Pump'  },
      { kind: 'vacuum_pump',        label: 'Vacuum Pump'       },
      { kind: 'turbine',            label: 'Turbine'           },
      { kind: 'steam_turbine',      label: 'Steam Turbine'     },
      { kind: 'gas_turbine',        label: 'Gas Turbine'       },
      { kind: 'electric_motor',     label: 'Electric Motor'    },
      { kind: 'gearbox',            label: 'Gearbox'           },
      { kind: 'centrifugal_blower', label: 'Centrifugal Blower'},
      { kind: 'roots_blower',       label: 'Roots Blower'      },
    ],
  },
  {
    title: 'Separation',
    items: [
      { kind: 'cyclone',    label: 'Cyclone'    },
      { kind: 'filter_pf',  label: 'Filter'     },
      { kind: 'centrifuge', label: 'Centrifuge' },
      { kind: 'membrane',   label: 'Membrane'   },
      { kind: 'decanter',        label: 'Decanter'          },
      { kind: 'clarifier',       label: 'Clarifier'         },
      { kind: 'three_phase_sep', label: 'Separator (3-Phase)' },
      { kind: 'oil_water_sep',   label: 'Oil-Water Separator' },
      { kind: 'esp',             label: 'Electrostatic Precip.' },
      { kind: 'demister',        label: 'Demister'          },
      { kind: 'coalescer',       label: 'Coalescer'         },
      { kind: 'settling_tank',   label: 'Settling Tank'     },
    ],
  },
  {
    title: 'Instruments',
    items: [
      { kind: 'ft', label: 'Flow (FT/FIC)'   },
      { kind: 'lt', label: 'Level (LT/LIC)'  },
      { kind: 'pt', label: 'Pressure (PT/PI)'},
      { kind: 'tt', label: 'Temp (TT/TI)'   },
      { kind: 'at', label: 'Analytical (AT)' },
      { kind: 'fe', label: 'Flow Element'    },
      { kind: 'le', label: 'Level Element'   },
      { kind: 'pe', label: 'Press Element'   },
      { kind: 'te', label: 'Temp Element'    },
    ],
  },
  {
    title: 'Control & Safety',
    items: [
      { kind: 'fic', label: 'Controller (FIC)'},
      { kind: 'fr',  label: 'Recorder'        },
      { kind: 'fsh', label: 'High Switch'      },
      { kind: 'fsl', label: 'Low Switch'       },
      { kind: 'dcs', label: 'DCS'              },
      { kind: 'plc', label: 'PLC'              },
      { kind: 'sis', label: 'SIS'              },
      { kind: 'pic', label: 'Pressure Ind. Controller (PIC)' },
      { kind: 'mfm', label: 'Mass Flow Meter (MFM)' },
      { kind: 'td',  label: 'Differential Temp (TD)' },
      { kind: 'ty',  label: 'Transducer (TY)'   },
      { kind: 'fy',  label: 'Transducer (FY)'   },
      { kind: 'oa',  label: 'Alarm (OA)'        },
      { kind: 'auto_man_selector', label: 'Auto/Manual Selector' },
    ],
  },
  {
    title: 'Valves',
    items: [
      { kind: 'cv_globe',    label: 'Globe (CV)'    },
      { kind: 'cv_ball',     label: 'Ball Valve'    },
      { kind: 'cv_butterfly',label: 'Butterfly'     },
      { kind: 'cv_gate',     label: 'Gate Valve'    },
      { kind: 'checkvalve',  label: 'Check Valve'   },
      { kind: 'psv',         label: 'PSV (Relief)'  },
      { kind: 'rupture_disc',label: 'Rupture Disc'  },
      { kind: 'three_way_valve',          label: '3-Way Valve'          },
      { kind: 'three_way_solenoid_valve', label: '3-Way Solenoid Valve' },
      { kind: 'normally_closed_valve',    label: 'Normally Closed Valve'},
      { kind: 'plug_valve',               label: 'Plug Valve'           },
      { kind: 'pcv',                      label: 'Pressure Regulator (PCV)' },
      { kind: 'back_pressure_regulator',  label: 'Back Pressure Regulator' },
      { kind: 'actuated_valve_general',   label: 'Actuated Valve (General)' },
    ],
  },
  {
    title: 'Equipment (Misc)',
    items: [
      { kind: 'mixing_tube',   label: 'Mixing Tube'   },
      { kind: 'micron_filter', label: 'Micron Filter' },
    ],
  },
  {
    title: 'Connectors',
    items: [
      { kind: 'on_page_connector', label: 'On-Page Connector' },
      { kind: 'continuation_arrow', label: 'Continuation Arrow' },
    ],
  },
  {
    title: 'Electrical',
    items: [
      { kind: 'motor',                 label: 'Motor'                 },
      { kind: 'hv_motor',              label: 'HV Motor'              },
      { kind: 'lv_motor',              label: 'LV Motor'              },
      { kind: 'vfd',                   label: 'VFD'                   },
      { kind: 'mcc',                   label: 'MCC'                   },
      { kind: 'generator',             label: 'Generator'             },
      { kind: 'diesel_generator',      label: 'Diesel Generator'      },
      { kind: 'transformer',           label: 'Transformer'           },
      { kind: 'ups',                   label: 'UPS'                   },
      { kind: 'battery_bank',          label: 'Battery Bank'          },
      { kind: 'switchboard',           label: 'Switchboard'           },
      { kind: 'distribution_panel',    label: 'Distribution Panel'    },
      { kind: 'junction_box',          label: 'Junction Box'          },
      { kind: 'terminal_box',          label: 'Terminal Box'          },
      { kind: 'control_panel',         label: 'Control Panel'         },
      { kind: 'local_control_station', label: 'Local Control Station' },
      { kind: 'disconnect_switch',     label: 'Disconnect Switch'     },
      { kind: 'circuit_breaker',       label: 'Circuit Breaker'       },
      { kind: 'fuse',                  label: 'Fuse'                  },
      { kind: 'ground',                label: 'Ground / Earth'        },
      { kind: 'lightning_protection',  label: 'Lightning Protection'  },
      { kind: 'cable_tray',            label: 'Cable Tray'            },
      { kind: 'cable_junction',        label: 'Cable Junction'        },
      { kind: 'lighting_fixture',      label: 'Lighting Fixture'      },
      { kind: 'emergency_lighting',    label: 'Emergency Lighting'    },
    ],
  },
  {
    title: 'Utilities',
    items: [
      { kind: 'steam_header',  label: 'Steam Header'    },
      { kind: 'steam_trap',    label: 'Steam Trap'       },
      { kind: 'steam_separator', label: 'Steam Separator'},
      { kind: 'steam_drum',    label: 'Steam Drum'       },
      { kind: 'util_cw',       label: 'Cooling Water'    },
      { kind: 'util_chw',      label: 'Chilled Water'    },
      { kind: 'util_bfw',      label: 'Boiler Feed Water'},
      { kind: 'util_cr',       label: 'Condensate Return'},
      { kind: 'util_hw',       label: 'Hot Water'        },
      { kind: 'util_ng',       label: 'Natural Gas'      },
      { kind: 'util_fg',       label: 'Fuel Gas'         },
      { kind: 'util_ia',       label: 'Instrument Air'   },
      { kind: 'util_pa',       label: 'Plant Air'        },
      { kind: 'util_n2',       label: 'Nitrogen'         },
      { kind: 'util_o2',       label: 'Oxygen'           },
      { kind: 'util_h2',       label: 'Hydrogen'         },
      { kind: 'util_ca',       label: 'Compressed Air'   },
      { kind: 'util_vac',      label: 'Vacuum Header'    },
      { kind: 'util_caustic',  label: 'Caustic'          },
      { kind: 'util_acid',     label: 'Acid'             },
      { kind: 'util_dmw',      label: 'Demin. Water'     },
      { kind: 'util_pw',       label: 'Process Water'    },
      { kind: 'util_potable',  label: 'Potable Water'    },
      { kind: 'util_header_main',   label: 'Main Utility Header'   },
      { kind: 'util_header_branch', label: 'Branch Utility Header' },
      { kind: 'util_header_dist',   label: 'Distribution Header'   },
    ],
  },
  {
    title: 'Fire & Safety',
    items: [
      { kind: 'fire_water_pump',   label: 'Fire Water Pump'   },
      { kind: 'jockey_pump',       label: 'Jockey Pump'       },
      { kind: 'diesel_fire_pump',  label: 'Diesel Fire Pump'  },
      { kind: 'deluge_valve',      label: 'Deluge Valve'      },
      { kind: 'fire_hydrant',      label: 'Fire Hydrant'      },
      { kind: 'sprinkler_head',    label: 'Sprinkler Head'    },
      { kind: 'water_monitor',     label: 'Water Monitor'     },
      { kind: 'foam_monitor',      label: 'Foam Monitor'      },
      { kind: 'smoke_detector',    label: 'Smoke Detector'    },
      { kind: 'heat_detector',     label: 'Heat Detector'     },
      { kind: 'flame_detector',    label: 'Flame Detector'    },
      { kind: 'gas_detector',      label: 'Gas Detector'      },
      { kind: 'toxic_gas_detector',label: 'Toxic Gas Detector'},
      { kind: 'emergency_shower',  label: 'Emergency Shower'  },
      { kind: 'eye_wash_station',  label: 'Eye Wash Station'  },
      { kind: 'safety_shower',     label: 'Safety Shower'     },
      { kind: 'escape_breathing_apparatus', label: 'Escape Breathing App.' },
      { kind: 'fire_extinguisher', label: 'Fire Extinguisher' },
      { kind: 'fire_alarm',        label: 'Fire Alarm'        },
      { kind: 'manual_call_point', label: 'Manual Call Point' },
      { kind: 'emergency_stop',    label: 'Emergency Stop'    },
      { kind: 'flame_arrestor',    label: 'Flame Arrestor'    },
      { kind: 'explosion_vent',    label: 'Explosion Vent'    },
      { kind: 'blast_relief_panel',label: 'Blast Relief Panel'},
      { kind: 'pressure_vent',     label: 'Pressure Vent'     },
      { kind: 'emergency_vent',    label: 'Emergency Vent'    },
    ],
  },
]

// ── Mini ISA preview icons ─────────────────────────────────────────────────────

// Vessels & Tanks — each kind gets its real ISA/ISO 10628 outline instead of
// falling through to the generic rounded-rect box below.
const VESSEL_ICON: Record<string, (color: string) => ReactElement> = {
  vessel_v: c => <VerticalVessel width={24} height={24} stroke={c} strokeWidth={1.6} />,
  vessel_h: c => <HorizontalVessel width={32} height={32} stroke={c} strokeWidth={1.6} />,
  flash_drum: c => <FlashDrum width={24} height={24} stroke={c} strokeWidth={1.6} />,
  knockout: c => <KnockoutDrum width={32} height={32} stroke={c} strokeWidth={1.6} />,
  accumulator: c => <Accumulator width={24} height={24} stroke={c} strokeWidth={1.6} />,
  tank_atm: c => <AtmosphericTank width={24} height={24} stroke={c} strokeWidth={1.6} />,
  hopper: c => <HopperSilo width={24} height={24} stroke={c} strokeWidth={1.6} />,
  sphere_vessel: c => <SphericalVessel width={26} height={26} stroke={c} strokeWidth={1.6} />,
  horton_sphere: c => <HortonSphere width={26} height={26} stroke={c} strokeWidth={1.6} />,
  bullet_tank: c => <BulletTank width={32} height={32} stroke={c} strokeWidth={1.6} />,
  tank_cone_roof: c => <AtmosphericTank width={24} height={24} stroke={c} strokeWidth={1.6} roof="cone" />,
  tank_dome_roof: c => <AtmosphericTank width={24} height={24} stroke={c} strokeWidth={1.6} roof="dome" />,
  tank_floating_roof: c => <AtmosphericTank width={24} height={24} stroke={c} strokeWidth={1.6} roof="floating" />,
  tank_ifr: c => <AtmosphericTank width={24} height={24} stroke={c} strokeWidth={1.6} roof="internal_floating" />,
  cryo_tank: c => <CryogenicTank width={24} height={24} stroke={c} strokeWidth={1.6} />,
  double_wall_tank: c => <DoubleWallTank width={24} height={24} stroke={c} strokeWidth={1.6} />,
}

// Columns & Towers — each kind gets its own internals (trays/packing/spray)
// instead of the generic tray-line box below.
const COLUMN_ICON: Record<string, (color: string) => ReactElement> = {
  dist_tray: c => <TrayColumn width={17} height={30} stroke={c} strokeWidth={1.6} />,
  column: c => <TrayColumn width={17} height={30} stroke={c} strokeWidth={1.6} />,
  dist_packed: c => <PackedColumn width={17} height={30} stroke={c} strokeWidth={1.6} />,
  absorber: c => <Absorber width={17} height={30} stroke={c} strokeWidth={1.6} />,
  scrubber: c => <Scrubber width={17} height={30} stroke={c} strokeWidth={1.6} />,
  stripper: c => <Stripper width={17} height={30} stroke={c} strokeWidth={1.6} />,
  dist_column: c => <DistillationColumn width={17} height={30} stroke={c} strokeWidth={1.6} />,
  fractionator: c => <Fractionator width={17} height={30} stroke={c} strokeWidth={1.6} />,
  deethanizer: c => <Deethanizer width={17} height={30} stroke={c} strokeWidth={1.6} />,
  debutanizer: c => <Debutanizer width={17} height={30} stroke={c} strokeWidth={1.6} />,
  stabilizer_column: c => <StabilizerColumn width={17} height={30} stroke={c} strokeWidth={1.6} />,
  vacuum_tower: c => <VacuumTower width={17} height={30} stroke={c} strokeWidth={1.6} />,
  reactor_column: c => <ReactorColumn width={17} height={30} stroke={c} strokeWidth={1.6} />,
}

// Reactors — agitator/bed/spray internals instead of a generic tall box.
const REACTOR_ICON: Record<string, (color: string) => ReactElement> = {
  cstr: c => <CSTR width={24} height={31} stroke={c} strokeWidth={1.6} />,
  pfr: c => <PFR width={32} height={20} stroke={c} strokeWidth={1.6} />,
  fixed_bed: c => <FixedBed width={24} height={31} stroke={c} strokeWidth={1.6} />,
  fluidized_bed: c => <FluidizedBed width={24} height={31} stroke={c} strokeWidth={1.6} />,
  batch_reactor: c => <BatchReactor width={24} height={31} stroke={c} strokeWidth={1.6} />,
  bubble_column_reactor: c => <BubbleColumnReactor width={24} height={31} stroke={c} strokeWidth={1.6} />,
  loop_reactor: c => <LoopReactor width={32} height={22} stroke={c} strokeWidth={1.6} />,
  slurry_reactor: c => <SlurryReactor width={24} height={31} stroke={c} strokeWidth={1.6} />,
  membrane_reactor: c => <MembraneReactor width={24} height={31} stroke={c} strokeWidth={1.6} />,
  trickle_bed_reactor: c => <TrickleBedReactor width={24} height={31} stroke={c} strokeWidth={1.6} />,
  catalytic_cracker: c => <CatalyticCracker width={27} height={30} stroke={c} strokeWidth={1.6} />,
  furnace_reactor: c => <FurnaceReactor width={22} height={26} stroke={c} strokeWidth={1.6} />,
}

// Heat Exchangers — tube bundle/plate pack/fan/burner internals per service type.
const HX_ICON: Record<string, (color: string) => ReactElement> = {
  hx_st: c => <ShellTube width={32} height={21} stroke={c} strokeWidth={1.6} />,
  hx_plate: c => <PlateHeatExchanger width={24} height={24} stroke={c} strokeWidth={1.6} />,
  condenser: c => <Condenser width={24} height={24} stroke={c} strokeWidth={1.6} />,
  reboiler_k: c => <Reboiler width={24} height={24} stroke={c} strokeWidth={1.6} />,
  air_cooler: c => <AirCooler width={32} height={20} stroke={c} strokeWidth={1.6} />,
  fired_heater: c => <FiredHeater width={22} height={26} stroke={c} strokeWidth={1.6} />,
  boiler: c => <Boiler width={22} height={26} stroke={c} strokeWidth={1.6} />,
  spiral_hx: c => <SpiralHX width={24} height={24} stroke={c} strokeWidth={1.6} />,
  double_pipe_hx: c => <DoublePipeHX width={30} height={20} stroke={c} strokeWidth={1.6} />,
  plate_frame_hx: c => <PlateFrameHX width={24} height={24} stroke={c} strokeWidth={1.6} />,
  hairpin_hx: c => <HairpinHX width={24} height={24} stroke={c} strokeWidth={1.6} />,
  evaporator: c => <Evaporator width={22} height={27} stroke={c} strokeWidth={1.6} />,
  economizer: c => <Economizer width={22} height={27} stroke={c} strokeWidth={1.6} />,
  superheater: c => <Superheater width={24} height={24} stroke={c} strokeWidth={1.6} />,
  waste_heat_boiler: c => <WasteHeatBoiler width={24} height={24} stroke={c} strokeWidth={1.6} />,
}

// Rotating equipment — real impeller/lobe/piston/blade internals per type.
const ROTATING_ICON: Record<string, (color: string) => ReactElement> = {
  pump_cent: c => <CentrifugalPump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  pump_pd: c => <PDPump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  comp_cent: () => <CentrifugalCompressor width={24} height={24} strokeWidth={1.6} />,
  comp_recip: () => <ReciprocatingCompressor width={24} height={24} strokeWidth={1.6} />,
  blower: () => <Blower width={24} height={24} strokeWidth={1.6} />,
  mixer: c => <Mixer width={24} height={24} stroke={c} strokeWidth={1.6} />,
  gear_pump: c => <GearPump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  screw_pump: c => <ScrewPump width={30} height={20} stroke={c} strokeWidth={1.6} />,
  diaphragm_pump: c => <DiaphragmPump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  peristaltic_pump: c => <PeristalticPump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  vacuum_pump: c => <VacuumPump width={30} height={22} stroke={c} strokeWidth={1.6} />,
  turbine: c => <Turbine width={30} height={21} stroke={c} strokeWidth={1.6} />,
  steam_turbine: c => <SteamTurbine width={30} height={21} stroke={c} strokeWidth={1.6} />,
  gas_turbine: c => <GasTurbine width={30} height={21} stroke={c} strokeWidth={1.6} />,
  electric_motor: c => <ElectricMotor width={28} height={20} stroke={c} strokeWidth={1.6} />,
  gearbox: c => <Gearbox width={28} height={20} stroke={c} strokeWidth={1.6} />,
  centrifugal_blower: c => <CentrifugalBlower width={24} height={24} stroke={c} strokeWidth={1.6} />,
  roots_blower: c => <RootsBlower width={28} height={20} stroke={c} strokeWidth={1.6} />,
}

// Separation — cyclone cone / pleated filter media / centrifuge basket / membrane layers.
const SEPARATION_ICON: Record<string, (color: string) => ReactElement> = {
  cyclone: c => <Cyclone width={24} height={24} stroke={c} strokeWidth={1.6} />,
  filter_pf: c => <FilterIcon width={26} height={19} stroke={c} strokeWidth={1.6} />,
  centrifuge: c => <Centrifuge width={24} height={21} stroke={c} strokeWidth={1.6} />,
  membrane: c => <Membrane width={26} height={19} stroke={c} strokeWidth={1.6} />,
  decanter: c => <Decanter width={30} height={20} stroke={c} strokeWidth={1.6} />,
  clarifier: c => <Clarifier width={24} height={24} stroke={c} strokeWidth={1.6} />,
  three_phase_sep: c => <ThreePhaseSeparator width={30} height={20} stroke={c} strokeWidth={1.6} />,
  oil_water_sep: c => <OilWaterSeparator width={30} height={20} stroke={c} strokeWidth={1.6} />,
  esp: c => <ElectrostaticPrecipitator width={24} height={24} stroke={c} strokeWidth={1.6} />,
  demister: c => <Demister width={22} height={24} stroke={c} strokeWidth={1.6} />,
  coalescer: c => <Coalescer width={22} height={24} stroke={c} strokeWidth={1.6} />,
  settling_tank: c => <SettlingTank width={24} height={24} stroke={c} strokeWidth={1.6} />,
}

// Valves — real ISO 10628 geometry (ball bore, butterfly disc, gate wedge,
// check hinge, API 526 PSV body, burst-disc membrane) instead of one bowtie
// shape shared by every valve type.
const VALVE_ICON: Record<string, (color: string) => ReactElement> = {
  cv_globe: c => <GlobeValve width={24} height={21} stroke={c} strokeWidth={1.6} />,
  cv_ball: c => <BallValve width={24} height={21} stroke={c} strokeWidth={1.6} />,
  cv_butterfly: c => <ButterflyValve width={24} height={21} stroke={c} strokeWidth={1.6} />,
  cv_gate: c => <GateValve width={21} height={24} stroke={c} strokeWidth={1.6} />,
  checkvalve: c => <CheckValve width={24} height={19} stroke={c} strokeWidth={1.6} />,
  psv: c => <PSV width={21} height={24} stroke={c} strokeWidth={1.6} />,
  rupture_disc: c => <RuptureDisc width={26} height={14} stroke={c} strokeWidth={1.6} />,
  three_way_valve: c => <ThreeWayValve width={24} height={25} stroke={c} strokeWidth={1.6} />,
  three_way_solenoid_valve: c => <ThreeWaySolenoidValve width={24} height={25} stroke={c} strokeWidth={1.6} />,
  normally_closed_valve: c => <NormallyClosedValve width={24} height={21} stroke={c} strokeWidth={1.6} />,
  plug_valve: c => <PlugValve width={24} height={21} stroke={c} strokeWidth={1.6} />,
  pcv: c => <PressureRegulatorPCV width={24} height={21} stroke={c} strokeWidth={1.6} />,
  back_pressure_regulator: c => <BackPressureRegulator width={24} height={21} stroke={c} strokeWidth={1.6} />,
  actuated_valve_general: c => <ActuatedValveGeneral width={24} height={21} stroke={c} strokeWidth={1.6} />,
}

// Control & Safety — dedicated ISA bubble/system-box per instrument type
// instead of every one collapsing into the same generic circle.
const CONTROL_ICON: Record<string, () => ReactElement> = {
  fic: () => <Controller width={24} height={24} strokeWidth={1.6} tagText="" />,
  fr: () => <Recorder width={24} height={24} strokeWidth={1.6} tagText="" />,
  fsh: () => <HighSwitch width={24} height={24} strokeWidth={1.6} tagText="" />,
  fsl: () => <LowSwitch width={24} height={24} strokeWidth={1.6} tagText="" />,
  dcs: () => <DCS width={24} height={24} strokeWidth={1.6} tagText="" />,
  plc: () => <PLC width={24} height={24} strokeWidth={1.6} tagText="" />,
  sis: () => <SIS width={24} height={24} strokeWidth={1.6} tagText="" />,
  pic: () => <Controller width={24} height={24} strokeWidth={1.6} tagText="" />,
  mfm: () => <MassFlowMeter width={24} height={24} strokeWidth={1.6} tagText="" />,
  td: () => <DifferentialTemperature width={24} height={24} strokeWidth={1.6} tagText="" />,
  ty: () => <Transducer width={22} height={27} strokeWidth={1.6} tagText="" />,
  fy: () => <Transducer width={22} height={27} strokeWidth={1.6} tagText="" />,
  oa: () => <Alarm width={24} height={24} strokeWidth={1.6} tagText="" />,
  auto_man_selector: () => <AutoManualSelector width={28} height={23} strokeWidth={1.6} />,
}

// Equipment (Misc) — small inline devices that don't fit an existing category.
const EQUIPMENT_MISC_ICON: Record<string, (color: string) => ReactElement> = {
  mixing_tube: c => <MixingTube width={30} height={20} stroke={c} strokeWidth={1.6} />,
  micron_filter: c => <MicronFilter width={22} height={24} stroke={c} strokeWidth={1.6} />,
}

// Connectors — on-page reference bubble + continuation arrow.
const CONNECTOR_ICON: Record<string, (color: string) => ReactElement> = {
  on_page_connector: c => <OnPageConnector width={22} height={22} stroke={c} strokeWidth={1.6} />,
  continuation_arrow: c => <ContinuationArrow width={28} height={16} stroke={c} strokeWidth={1.6} />,
}

// Electrical — IEC 60617 motor/generator circles, panel/cabinet outlines,
// and standard breaker/fuse/ground/lighting symbols.
const ELECTRICAL_ICON: Record<string, (color: string) => ReactElement> = {
  motor: c => <Motor width={24} height={24} stroke={c} strokeWidth={1.6} />,
  hv_motor: c => <HighVoltageMotor width={24} height={24} stroke={c} strokeWidth={1.6} />,
  lv_motor: c => <LowVoltageMotor width={24} height={24} stroke={c} strokeWidth={1.6} />,
  vfd: c => <VFD width={24} height={24} stroke={c} strokeWidth={1.6} />,
  mcc: c => <MCC width={22} height={26} stroke={c} strokeWidth={1.6} />,
  generator: c => <Generator width={22} height={24} stroke={c} strokeWidth={1.6} />,
  diesel_generator: c => <DieselGenerator width={22} height={26} stroke={c} strokeWidth={1.6} />,
  transformer: c => <Transformer width={20} height={24} stroke={c} strokeWidth={1.6} />,
  ups: c => <UPS width={24} height={24} stroke={c} strokeWidth={1.6} />,
  battery_bank: c => <BatteryBank width={28} height={18} stroke={c} strokeWidth={1.6} />,
  switchboard: c => <Switchboard width={24} height={24} stroke={c} strokeWidth={1.6} />,
  distribution_panel: c => <DistributionPanel width={24} height={24} stroke={c} strokeWidth={1.6} />,
  junction_box: c => <JunctionBox width={22} height={22} stroke={c} strokeWidth={1.6} />,
  terminal_box: c => <TerminalBox width={26} height={16} stroke={c} strokeWidth={1.6} />,
  control_panel: c => <ControlPanel width={24} height={24} stroke={c} strokeWidth={1.6} />,
  local_control_station: c => <LocalControlStation width={24} height={24} stroke={c} strokeWidth={1.6} />,
  disconnect_switch: c => <DisconnectSwitch width={18} height={24} stroke={c} strokeWidth={1.6} />,
  circuit_breaker: c => <CircuitBreaker width={16} height={24} stroke={c} strokeWidth={1.6} />,
  fuse: c => <Fuse width={16} height={24} stroke={c} strokeWidth={1.6} />,
  ground: c => <Ground width={20} height={22} stroke={c} strokeWidth={1.6} />,
  lightning_protection: c => <LightningProtection width={20} height={22} stroke={c} strokeWidth={1.6} />,
  cable_tray: c => <CableTray width={28} height={18} stroke={c} strokeWidth={1.6} />,
  cable_junction: c => <CableJunction width={26} height={22} stroke={c} strokeWidth={1.6} />,
  lighting_fixture: c => <LightingFixture width={24} height={24} stroke={c} strokeWidth={1.6} />,
  emergency_lighting: c => <EmergencyLighting width={24} height={24} stroke={c} strokeWidth={1.6} />,
}

// Utilities — real steam equipment gets a real symbol; every other service
// (cooling water, nitrogen, caustic, etc.) shares one generic line/tag
// component per ISA/ISO line-type convention, distinguished only by its
// service code + dash pattern, not by a fake unique shape.
const UTIL_LINE_STYLE: Record<string, { code: string; dash: 'solid' | 'dashed' | 'dash-dot' | 'dash-dot-dot' }> = {
  util_cw: { code: 'CW', dash: 'solid' },
  util_chw: { code: 'CHW', dash: 'dashed' },
  util_bfw: { code: 'BFW', dash: 'solid' },
  util_cr: { code: 'CR', dash: 'dashed' },
  util_hw: { code: 'HW', dash: 'solid' },
  util_ng: { code: 'NG', dash: 'dash-dot' },
  util_fg: { code: 'FG', dash: 'dash-dot' },
  util_ia: { code: 'IA', dash: 'dash-dot-dot' },
  util_pa: { code: 'PA', dash: 'dash-dot-dot' },
  util_n2: { code: 'N2', dash: 'dash-dot' },
  util_o2: { code: 'O2', dash: 'dash-dot' },
  util_h2: { code: 'H2', dash: 'dash-dot' },
  util_ca: { code: 'CA', dash: 'dash-dot-dot' },
  util_vac: { code: 'VAC', dash: 'dashed' },
  util_caustic: { code: 'CAU', dash: 'solid' },
  util_acid: { code: 'ACD', dash: 'solid' },
  util_dmw: { code: 'DMW', dash: 'solid' },
  util_pw: { code: 'PW', dash: 'solid' },
  util_potable: { code: 'POT', dash: 'solid' },
}
const UTILITY_ICON: Record<string, (color: string) => ReactElement> = {
  steam_header: c => <SteamHeader width={28} height={20} stroke={c} strokeWidth={1.6} />,
  steam_trap: c => <SteamTrap width={26} height={16} stroke={c} strokeWidth={1.6} />,
  steam_separator: c => <SteamSeparator width={20} height={26} stroke={c} strokeWidth={1.6} />,
  steam_drum: c => <SteamDrum width={28} height={18} stroke={c} strokeWidth={1.6} />,
  util_header_main: c => <UtilityHeader width={28} height={20} stroke={c} strokeWidth={1.6} />,
  util_header_branch: c => <UtilityHeader width={28} height={20} stroke={c} strokeWidth={1.6} />,
  util_header_dist: c => <UtilityHeader width={28} height={20} stroke={c} strokeWidth={1.6} />,
}
function utilityLineIcon(kind: string, color: string) {
  const svc = UTIL_LINE_STYLE[kind]
  return <UtilityLine width={28} height={16} stroke={color} strokeWidth={1.6}
    serviceCode={svc?.code ?? ''} lineStyle={svc?.dash ?? 'solid'} />
}

// Fire & Safety — real distinct devices throughout (pumps, detectors,
// emergency equipment, protection devices).
const FIRE_SAFETY_ICON: Record<string, (color: string) => ReactElement> = {
  fire_water_pump: c => <FireWaterPump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  jockey_pump: c => <JockeyPump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  diesel_fire_pump: c => <DieselFirePump width={24} height={24} stroke={c} strokeWidth={1.6} />,
  deluge_valve: c => <DelugeValve width={24} height={21} stroke={c} strokeWidth={1.6} />,
  fire_hydrant: c => <FireHydrant width={24} height={21} stroke={c} strokeWidth={1.6} />,
  sprinkler_head: c => <SprinklerHead width={24} height={24} stroke={c} strokeWidth={1.6} />,
  water_monitor: c => <WaterMonitor width={24} height={24} stroke={c} strokeWidth={1.6} />,
  foam_monitor: c => <FoamMonitor width={24} height={24} stroke={c} strokeWidth={1.6} />,
  smoke_detector: c => <SmokeDetector width={24} height={19} stroke={c} strokeWidth={1.6} />,
  heat_detector: c => <HeatDetector width={24} height={19} stroke={c} strokeWidth={1.6} />,
  flame_detector: c => <FlameDetector width={24} height={22} stroke={c} strokeWidth={1.6} />,
  gas_detector: c => <GasDetector width={24} height={22} stroke={c} strokeWidth={1.6} />,
  toxic_gas_detector: c => <ToxicGasDetector width={24} height={22} stroke={c} strokeWidth={1.6} />,
  emergency_shower: c => <EmergencyShower width={24} height={24} stroke={c} strokeWidth={1.6} />,
  eye_wash_station: c => <EyeWashStation width={24} height={24} stroke={c} strokeWidth={1.6} />,
  safety_shower: c => <SafetyShower width={24} height={24} stroke={c} strokeWidth={1.6} />,
  escape_breathing_apparatus: c => <EscapeBreathingApparatus width={24} height={24} stroke={c} strokeWidth={1.6} />,
  fire_extinguisher: c => <FireExtinguisher width={22} height={24} stroke={c} strokeWidth={1.6} />,
  fire_alarm: c => <FireAlarm width={24} height={24} stroke={c} strokeWidth={1.6} />,
  manual_call_point: c => <ManualCallPoint width={24} height={24} stroke={c} strokeWidth={1.6} />,
  emergency_stop: c => <EmergencyStop width={24} height={24} stroke={c} strokeWidth={1.6} />,
  flame_arrestor: c => <FlameArrestor width={24} height={21} stroke={c} strokeWidth={1.6} />,
  explosion_vent: c => <ExplosionVent width={24} height={24} stroke={c} strokeWidth={1.6} />,
  blast_relief_panel: c => <BlastReliefPanel width={24} height={24} stroke={c} strokeWidth={1.6} />,
  pressure_vent: c => <PressureVent width={22} height={24} stroke={c} strokeWidth={1.6} />,
  emergency_vent: c => <EmergencyVent width={22} height={24} stroke={c} strokeWidth={1.6} />,
}

const INSTR_KINDS = new Set([
  'ft','lt','pt','tt','at','fe','le','pe','te',
])
const INSTR_COLOR: Record<string, string> = {
  ft: '#0ea5e9', lt: '#22c55e', pt: '#a855f7',
  tt: '#ef4444', at: '#eab308', fe: '#0ea5e9',
  le: '#22c55e', pe: '#a855f7', te: '#ef4444',
}

function PaletteIcon({ kind }: { kind: string }) {
  if (VESSEL_ICON[kind]) {
    const c = equipColors(kind).border
    return (
      <div style={{ width: 32, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {VESSEL_ICON[kind](c)}
      </div>
    )
  }
  if (COLUMN_ICON[kind]) {
    const c = equipColors('column').border
    return (
      <div style={{ width: 24, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {COLUMN_ICON[kind](c)}
      </div>
    )
  }
  if (REACTOR_ICON[kind]) {
    const c = equipColors('reactor').border
    return (
      <div style={{ width: 24, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {REACTOR_ICON[kind](c)}
      </div>
    )
  }
  if (HX_ICON[kind]) {
    const c = equipColors('heat_exchanger').border
    return (
      <div style={{ width: 32, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {HX_ICON[kind](c)}
      </div>
    )
  }
  if (ROTATING_ICON[kind]) {
    const c = equipColors(kind).border
    return (
      <div style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {ROTATING_ICON[kind](c)}
      </div>
    )
  }
  if (SEPARATION_ICON[kind]) {
    const c = equipColors(kind).border
    return (
      <div style={{ width: 28, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {SEPARATION_ICON[kind](c)}
      </div>
    )
  }
  if (VALVE_ICON[kind]) {
    return (
      <div style={{ width: 28, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {VALVE_ICON[kind](VALVE_C.border)}
      </div>
    )
  }
  if (CONTROL_ICON[kind]) {
    return (
      <div style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {CONTROL_ICON[kind]()}
      </div>
    )
  }
  if (ELECTRICAL_ICON[kind]) {
    const c = equipColors('motor').border
    return (
      <div style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {ELECTRICAL_ICON[kind](c)}
      </div>
    )
  }
  if (UTILITY_ICON[kind]) {
    const c = equipColors('steam_trap').border
    return (
      <div style={{ width: 32, height: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {UTILITY_ICON[kind](c)}
      </div>
    )
  }
  if (UTIL_LINE_STYLE[kind]) {
    const c = equipColors('steam_trap').border
    return (
      <div style={{ width: 32, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {utilityLineIcon(kind, c)}
      </div>
    )
  }
  if (FIRE_SAFETY_ICON[kind]) {
    const c = equipColors('fire_water_pump').border
    return (
      <div style={{ width: 28, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {FIRE_SAFETY_ICON[kind](c)}
      </div>
    )
  }
  if (EQUIPMENT_MISC_ICON[kind]) {
    const c = equipColors('filter').border
    return (
      <div style={{ width: 32, height: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {EQUIPMENT_MISC_ICON[kind](c)}
      </div>
    )
  }
  if (CONNECTOR_ICON[kind]) {
    const c = '#64748B'
    return (
      <div style={{ width: 28, height: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {CONNECTOR_ICON[kind](c)}
      </div>
    )
  }
  if (INSTR_KINDS.has(kind)) {
    const c = INSTR_COLOR[kind] ?? '#f59e0b'
    return (
      <svg width="22" height="22" viewBox="0 0 18 18" style={{ flexShrink: 0 }}>
        <circle cx="9" cy="9" r="7.5" fill="none" stroke={c} strokeWidth="1.5"/>
      </svg>
    )
  }
  const c = equipColors(kind)
  // Default: horizontal rounded rect (vessel, tank, etc.)
  return (
    <svg width="30" height="17" viewBox="0 0 28 16" style={{ flexShrink: 0 }}>
      <rect x="1" y="1" width="26" height="14" rx="6" fill="none" stroke={c.border} strokeWidth="1.5"/>
    </svg>
  )
}

// ── Palette panel ─────────────────────────────────────────────────────────────

export default function DrawPalette({ onSelectKind, placingKind }: {
  onSelectKind: (kind: string | null) => void
  placingKind: string | null
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  function toggle(title: string) {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(title)) next.delete(title)
      else next.add(title)
      return next
    })
  }

  return (
    <div style={{
      width: 148, flexShrink: 0,
      borderRight: '1px solid var(--border)',
      background: 'var(--bg-secondary)',
      overflowY: 'auto',
      display: 'flex', flexDirection: 'column',
      paddingBottom: 16,
    }}>
      <div style={{
        position: 'sticky', top: 0, zIndex: 1,
        background: 'var(--bg-secondary)',
        padding: '10px 10px 6px',
        borderBottom: '1px solid var(--border)',
      }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.1em', textTransform: 'uppercase', opacity: 0.8 }}>
          Draw Palette
        </div>
        <div style={{ fontSize: 9, color: placingKind ? 'var(--accent)' : 'var(--text-muted)', marginTop: 3, lineHeight: 1.4 }}>
          {placingKind ? 'Click on canvas to place' : 'Click, or drag onto canvas'}
        </div>
      </div>

      {PALETTE_GROUPS.map(group => {
        const isCollapsed = collapsed.has(group.title)
        return (
          <div key={group.title}>
            {/* Collapsible group header */}
            <button
              onClick={() => toggle(group.title)}
              style={{
                width: '100%', textAlign: 'left', background: 'none',
                border: 'none', borderBottom: '1px solid var(--border)',
                padding: '5px 10px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-tertiary)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'none' }}
            >
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                {group.title}
              </span>
              <span style={{ fontSize: 9, color: 'var(--text-muted)', lineHeight: 1 }}>
                {isCollapsed ? '▸' : '▾'}
              </span>
            </button>

            {/* Items */}
            {!isCollapsed && group.items.map((item, idx) => {
              const isSelected = placingKind === item.kind
              return (
              <div
                key={`${item.kind}-${idx}`}
                draggable
                onDragStart={e => { e.dataTransfer.setData('application/x-palette-kind', item.kind); e.dataTransfer.effectAllowed = 'copy' }}
                onClick={() => onSelectKind(isSelected ? null : item.kind)}
                title={`Click to place ${item.label}, or drag onto the canvas`}
                style={{
                  display: 'flex', alignItems: 'center', gap: 7,
                  padding: '4px 10px', cursor: 'grab',
                  margin: '1px 3px', borderRadius: 4,
                  userSelect: 'none',
                  background: isSelected ? 'rgba(59,130,246,0.15)' : 'transparent',
                  outline: isSelected ? '1px solid rgba(59,130,246,0.5)' : 'none',
                }}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-tertiary)' }}
                onMouseLeave={e => { e.currentTarget.style.background = isSelected ? 'rgba(59,130,246,0.15)' : 'transparent' }}
              >
                <div style={{ width: 36, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <PaletteIcon kind={item.kind} />
                </div>
                <span style={{ flex: 1, minWidth: 0, fontSize: 10.5, color: 'var(--text-secondary)', lineHeight: 1.2, wordBreak: 'break-word' }}>
                  {item.label}
                </span>
              </div>
            )})}
          </div>
        )
      })}
    </div>
  )
}

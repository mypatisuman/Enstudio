import type { ReactNode, ReactElement } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import { Theme, STROKE } from './theme'
import { VerticalBody, HorizontalBody } from '../pid-symbols/vessels/primitives'
import {
  AtmosphericTank, SphericalVessel, HortonSphere, BulletTank, CryogenicTank, DoubleWallTank,
} from '../pid-symbols/vessels'
import { VacuumTower, ReactorColumn } from '../pid-symbols/columns'
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
// Pure ISA classification/color/sizing logic lives in the framework-independent
// domain module — re-exported here unchanged so existing imports of this file
// (CanvasScreen, processLayout, DrawPalette) don't need to change.
import {
  equipColors, VALVE_C, OFFPAGE_C, VALVE_RE, isValveTag, instrColors, formatTag, fitTag,
  getNodeType, getNodeSize,
} from '../../domain/isa/classification'
export { equipColors, VALVE_C, OFFPAGE_C, VALVE_RE, isValveTag, instrColors, getNodeType, getNodeSize }

export interface ISANodeData {
  label: string; kind: string; kind_detail: string
  area: string; drawing: string; equipment_ref: string
  softChildren: Array<{ id: string; label: string; kind: string; area: string }>
  [key: string]: unknown
}

// ── Handles ───────────────────────────────────────────────────────────────────
const H_STYLE = { opacity: 0, width: 8, height: 8 }
function AllHandles() {
  return <>
    <Handle type="source" position={Position.Left} style={H_STYLE} id="sl" />
    <Handle type="source" position={Position.Right} style={H_STYLE} id="sr" />
    <Handle type="source" position={Position.Top} style={H_STYLE} id="st" />
    <Handle type="source" position={Position.Bottom} style={H_STYLE} id="sb" />
    <Handle type="target" position={Position.Left} style={H_STYLE} id="tl" />
    <Handle type="target" position={Position.Right} style={H_STYLE} id="tr" />
    <Handle type="target" position={Position.Top} style={H_STYLE} id="tt" />
    <Handle type="target" position={Position.Bottom} style={H_STYLE} id="tb" />
  </>
}

// Junctions are a dot centred in a 16px hit body. Edge-anchored handles would
// end an incoming pipe at the box edge (8px off the dot), so the arrowhead
// stops short. Pin every handle to the node CENTRE so any side resolves to the
// dot itself and the pipe/arrow reaches it exactly.
const H_STYLE_CENTER = { ...H_STYLE, left: '50%', top: '50%', transform: 'translate(-50%,-50%)' }
function CenterHandles() {
  return <>
    <Handle type="source" position={Position.Left} style={H_STYLE_CENTER} id="sl" />
    <Handle type="source" position={Position.Right} style={H_STYLE_CENTER} id="sr" />
    <Handle type="source" position={Position.Top} style={H_STYLE_CENTER} id="st" />
    <Handle type="source" position={Position.Bottom} style={H_STYLE_CENTER} id="sb" />
    <Handle type="target" position={Position.Left} style={H_STYLE_CENTER} id="tl" />
    <Handle type="target" position={Position.Right} style={H_STYLE_CENTER} id="tr" />
    <Handle type="target" position={Position.Top} style={H_STYLE_CENTER} id="tt" />
    <Handle type="target" position={Position.Bottom} style={H_STYLE_CENTER} id="tb" />
  </>
}

// ── Valve tag label, rendered BELOW the symbol (ISA convention) ───────────────
// Overflows the node bounds downward so the symbol stays centered on the pipe.
function ValveLabel({ text, color = '#94a3b8' }: { text: string; color?: string }) {
  return (
    <div style={{
      position: 'absolute', top: '100%', left: '50%',
      transform: 'translateX(-50%)', marginTop: 2,
      fontSize: 8, lineHeight: 1, whiteSpace: 'nowrap',
      maxWidth: 72, overflow: 'hidden', textOverflow: 'ellipsis',
      color, fontWeight: 700,
      pointerEvents: 'none',
    }} className="isa-tag">{formatTag(text)}</div>
  )
}

// ── Instrument bubble ─────────────────────────────────────────────────────────
// Plain solid circle = field-mounted (ISA default)
// Circle with horizontal line = panel/board-mounted (controller, indicator)
function InstrumentNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const kind = String(data.kind ?? '').toLowerCase()
  const { bg, border, text } = instrColors(lbl)
  const sc = (data.softChildren ?? []).length
  const vbH = sc > 0 ? 62 : 50

  const m = lbl.match(/^([A-Za-z]+)[-]?(.*)$/)
  const funcCode = m?.[1] ?? lbl
  const loopNum = m?.[2] ?? ''

  // Panel-mounted: controller, indicator — draw horizontal line through middle
  const isPanelMounted = ['controller', 'indicator', 'recorder'].includes(kind)

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox={`0 0 50 ${vbH}`} xmlns="http://www.w3.org/2000/svg">
        <circle cx="25" cy="25" r="22" fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.symbol} />
        {isPanelMounted && (
          <line x1="3" y1="25" x2="47" y2="25" stroke={border} strokeWidth={STROKE.signal} opacity="0.8" />
        )}
        <text className="isa-tag" x="25" y={loopNum ? '20' : '25'} textAnchor="middle" dominantBaseline="central"
          fontSize={funcCode.length > 3 ? '9' : '11'} fontWeight="800"
          fill={text} fontFamily="monospace,'Courier New'">{funcCode}</text>
        {loopNum && (
          <text className="isa-detail" x="25" y="33" textAnchor="middle" dominantBaseline="central"
            fontSize="8" fill={text} fontFamily="monospace,'Courier New'">{loopNum}</text>
        )}
        {sc > 0 && (
          <text className="isa-detail" x="25" y="55" textAnchor="middle" dominantBaseline="central"
            fontSize="7" fill="#475569">+{sc}</text>
        )}
      </svg>
    </div>
  )
}

// ── DCS / Computer function — square box with inscribed circle (ISA 5.1) ────────────
function DcsFuncNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = instrColors(lbl)
  const m = lbl.match(/^([A-Za-z]+)[-]?(.*)$/)
  const funcCode = m?.[1] ?? lbl
  const loopNum = m?.[2] ?? ''
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 50 50" xmlns="http://www.w3.org/2000/svg">
        <rect x="3" y="3" width="44" height="44" fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.symbol} />
        <circle cx="25" cy="25" r="22" fill="none" stroke={border} strokeWidth={STROKE.signal} opacity="0.6" />
        <text className="isa-tag" x="25" y={loopNum ? '18' : '25'} textAnchor="middle" dominantBaseline="central"
          fontSize={funcCode.length > 3 ? '9' : '11'} fontWeight="800"
          fill={text} fontFamily="monospace,'Courier New'">{funcCode}</text>
        {loopNum && (
          <text className="isa-detail" x="25" y="34" textAnchor="middle" dominantBaseline="central"
            fontSize="8" fill={text} fontFamily="monospace,'Courier New'">{loopNum}</text>
        )}
      </svg>
    </div>
  )
}

// ── SIS / Safety function — diamond (ISA 5.1) ─────────────────────────────────
function SisFuncNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = instrColors(lbl)
  const m = lbl.match(/^([A-Za-z]+)[-]?(.*)$/)
  const funcCode = m?.[1] ?? lbl
  const loopNum = m?.[2] ?? ''
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 50 50" xmlns="http://www.w3.org/2000/svg">
        <polygon points="25,2 48,25 25,48 2,25"
          fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.symbol} />
        <text className="isa-tag" x="25" y={loopNum ? '20' : '25'} textAnchor="middle" dominantBaseline="central"
          fontSize={funcCode.length > 3 ? '8' : '10'} fontWeight="800"
          fill={text} fontFamily="monospace,'Courier New'">{funcCode}</text>
        {loopNum && (
          <text className="isa-detail" x="25" y="32" textAnchor="middle" dominantBaseline="central"
            fontSize="8" fill={text} fontFamily="monospace,'Courier New'">{loopNum}</text>
        )}
      </svg>
    </div>
  )
}

// ── Level glass — narrow rectangle beside vessel (ISA 5.1) ────────────────────
function LevelGlassNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = instrColors(lbl)
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 16 50" xmlns="http://www.w3.org/2000/svg">
        <rect x="2" y="2" width="12" height="46" fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.signal} />
        {/* Fill level indicator — top third shaded */}
        <rect x="3" y="3" width="10" height="15" fill={border} opacity="0.35" />
        <text className="isa-tag" x="8" y="40" textAnchor="middle" dominantBaseline="central"
          fontSize="5" fill={text} fontFamily="monospace,'Courier New'"
          transform="rotate(-90 8 40)">{lbl}</text>
      </svg>
    </div>
  )
}

// ── Valve / control-system nodes reusing pid-symbols ──────────────────────────
// Same reuse pattern as reactors/HX/rotating: the icon component IS the
// canvas shape. Valves keep the app's existing tag-driven color lookup
// (instrColors) and below-shape ValveLabel; control-system boxes use their
// own spec-mandated fixed colors and render the tag INSIDE the symbol, so no
// separate label is needed.
type ValveIcon = (props: { width?: number; height?: number; stroke?: string; strokeWidth?: number; selected?: boolean }) => ReactElement
type ControlIcon = (props: { width?: number; height?: number; selected?: boolean; tagText?: string }) => ReactElement

function valveIconNode(Icon: ValveIcon, w: number, h: number) {
  return function IconNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
    const lbl = String(data.label ?? '')
    const { border } = instrColors(lbl)
    return (
      <div style={{ width: '100%', height: '100%', position: 'relative' }}>
        <AllHandles />
        <Icon width={w} height={h} stroke={border} strokeWidth={STROKE.signal} selected={selected} />
        <ValveLabel text={lbl} color={border} />
      </div>
    )
  }
}

function controlIconNode(Icon: ControlIcon, w: number, h: number) {
  return function IconNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
    const lbl = String(data.label ?? '')
    const tag = lbl.match(/^([A-Za-z]+)/)?.[1]
    return (
      <div style={{ width: '100%', height: '100%', position: 'relative' }}>
        <AllHandles />
        <Icon width={w} height={h} selected={selected} tagText={tag} />
      </div>
    )
  }
}

const ValveNode = valveIconNode(GlobeValve, 52, 46)
const BallValveNode = valveIconNode(BallValve, 54, 50)
const ButterflyValveNode = valveIconNode(ButterflyValve, 54, 50)
const GateValveNode = valveIconNode(GateValve, 54, 56)
const CheckValveNode = valveIconNode(CheckValve, 44, 32)
const ReliefValveNode = valveIconNode(PSV, 52, 44)
const RuptureDiscNode = valveIconNode(RuptureDisc, 50, 30)
const ThreeWayValveNode = valveIconNode(ThreeWayValve, 54, 56)
const ThreeWaySolenoidValveNode = valveIconNode(ThreeWaySolenoidValve, 54, 56)
const NormallyClosedValveNode = valveIconNode(NormallyClosedValve, 54, 50)
const PlugValveNode = valveIconNode(PlugValve, 54, 50)
const PcvNode = valveIconNode(PressureRegulatorPCV, 54, 50)
const BackPressureRegulatorNode = valveIconNode(BackPressureRegulator, 54, 50)
const ActuatedValveGeneralNode = valveIconNode(ActuatedValveGeneral, 54, 50)

const ControllerNode = controlIconNode(Controller, 52, 52)
const RecorderNode = controlIconNode(Recorder, 52, 52)
const HighSwitchNode = controlIconNode(HighSwitch, 52, 52)
const LowSwitchNode = controlIconNode(LowSwitch, 52, 52)
const DcsCtrlNode = controlIconNode(DCS, 64, 64)
const PlcCtrlNode = controlIconNode(PLC, 64, 64)
const SisCtrlNode = controlIconNode(SIS, 64, 64)
const MfmNode = controlIconNode(MassFlowMeter, 52, 52)
const TdNode = controlIconNode(DifferentialTemperature, 52, 52)
const TransducerNode = controlIconNode(Transducer, 52, 64)
const AlarmNode = controlIconNode(Alarm, 52, 52)
const AutoManSelectorNode = controlIconNode(AutoManualSelector, 64, 52)

const MixingTubeNode = symbolIconNode(MixingTube, 70, 46, 'filter')
const MicronFilterNode = symbolIconNode(MicronFilter, 60, 66, 'filter')
const OnPageConnectorNode = symbolIconNode(OnPageConnector, 52, 52, 'connector')
const ContinuationArrowNode = symbolIconNode(ContinuationArrow, 56, 32, 'connector')

// ── Regulator — open bowtie + diaphragm actuator + sensing line (ISA 5.1) ──
function RegulatorNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border } = instrColors(lbl)
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 52 46" xmlns="http://www.w3.org/2000/svg">
        {/* Diaphragm actuator */}
        <line x1="26" y1="16" x2="26" y2="9" stroke={stroke} strokeWidth={STROKE.signal} />
        <path d="M 16,9 A 10 7 0 0 1 36,9 Z" fill="none" stroke={stroke} strokeWidth={STROKE.signal} />
        {/* Open bowtie body */}
        <polygon points="2,16 2,44 26,30" fill={bg} stroke={stroke} strokeWidth={STROKE.signal} strokeLinejoin="round" />
        <polygon points="50,16 50,44 26,30" fill={bg} stroke={stroke} strokeWidth={STROKE.signal} strokeLinejoin="round" />
        {/* Internal sensing line (downstream) */}
        <polyline points="36,9 42,9 42,30" fill="none" stroke={stroke} strokeWidth="1" strokeDasharray="3 2" />
      </svg>
      <ValveLabel text={lbl} color={border} />
    </div>
  )
}

// ── Hand valve — open bowtie with T stem (manual valve), label below (ISA 5.1) ──
function HandValveNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border } = instrColors(lbl)
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 44 32" xmlns="http://www.w3.org/2000/svg">
        {/* Open bowtie body */}
        <polygon points="2,8 2,30 22,19" fill={bg} stroke={stroke} strokeWidth={STROKE.signal} strokeLinejoin="round" />
        <polygon points="42,8 42,30 22,19" fill={bg} stroke={stroke} strokeWidth={STROKE.signal} strokeLinejoin="round" />
        {/* Handwheel T-stem */}
        <line x1="22" y1="19" x2="22" y2="4" stroke={stroke} strokeWidth={STROKE.signal} />
        <line x1="16" y1="4" x2="28" y2="4" stroke={stroke} strokeWidth={STROKE.signal} />
      </svg>
      <ValveLabel text={lbl} color={border} />
    </div>
  )
}


// ── Orifice plate — two perpendicular lines across pipe (ISA 5.1, 36×32) ──────
function OrificeNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { border } = VALVE_C
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 36 32" xmlns="http://www.w3.org/2000/svg">
        {/* Pipe centerline */}
        <line x1="2" y1="16" x2="34" y2="16" stroke={stroke} strokeWidth={STROKE.signal} />
        {/* Orifice plate — vertical bar with gap */}
        <line x1="18" y1="2" x2="18" y2="12" stroke={stroke} strokeWidth="3" strokeLinecap="square" />
        <line x1="18" y1="20" x2="18" y2="30" stroke={stroke} strokeWidth="3" strokeLinecap="square" />
      </svg>
      <ValveLabel text={lbl} color={border} />
    </div>
  )
}

// ── Needle valve — triangle + line through tip (ISA 5.1, 40×32) ──────────────
function NeedleValveNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { border } = instrColors(lbl)
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 40 32" xmlns="http://www.w3.org/2000/svg">
        <polygon points="2,2 2,30 38,16"
          fill={stroke} stroke={stroke} strokeWidth={STROKE.signal} strokeLinejoin="round" />
        {/* Line through tip — needle indicator */}
        <line x1="30" y1="8" x2="38" y2="24" stroke={border} strokeWidth={STROKE.signal} />
      </svg>
      <ValveLabel text={lbl} color={border} />
    </div>
  )
}

// ── Solenoid valve — bowtie + solenoid coil on top (ISA 5.1, 52×40) ──────────
function SolenoidValveNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border } = instrColors(lbl)
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 52 40" xmlns="http://www.w3.org/2000/svg">
        {/* Open bowtie body */}
        <polygon points="2,14 2,38 26,26" fill={bg} stroke={stroke} strokeWidth={STROKE.signal} strokeLinejoin="round" />
        <polygon points="50,14 50,38 26,26" fill={bg} stroke={stroke} strokeWidth={STROKE.signal} strokeLinejoin="round" />
        {/* Solenoid coil rectangle on top */}
        <rect x="16" y="2" width="20" height="10" fill={bg} stroke={stroke} strokeWidth="1.2" />
        <text x="26" y="7" textAnchor="middle" dominantBaseline="central"
          fontSize="6" fontWeight="700" fill={border} fontFamily="monospace,'Courier New'">S</text>
        <line x1="26" y1="12" x2="26" y2="14" stroke={stroke} strokeWidth="1.2" />
      </svg>
      <ValveLabel text={lbl} color={border} />
    </div>
  )
}

// ── Rotating equipment / separation nodes ──────────────────────────────────────
// Same reuse pattern as the reactor/HX nodes above: the pid-symbols icon IS
// the canvas shape, letterboxed to fit via preserveAspectRatio, with the tag
// below via ValveLabel. equipColors('pump')/('compressor') border colors
// already match the rotating library's green/indigo palette, so passing
// `border` through as the icon stroke stays on-spec.
const CentrifugalPumpNode = symbolIconNode(CentrifugalPump, 62, 62, 'pump')
const PdPumpNode = symbolIconNode(PDPump, 62, 62, 'pump')
const MixerNode = symbolIconNode(Mixer, 64, 64, 'pump')
const CentrifugalCompressorNode = symbolIconNode(CentrifugalCompressor, 70, 70, 'compressor')
const ReciprocatingCompressorNode = symbolIconNode(ReciprocatingCompressor, 70, 70, 'compressor')
const BlowerNode = symbolIconNode(Blower, 70, 70, 'compressor')

const GearPumpNode = symbolIconNode(GearPump, 62, 62, 'pump')
const DiaphragmPumpNode = symbolIconNode(DiaphragmPump, 62, 62, 'pump')
const PeristalticPumpNode = symbolIconNode(PeristalticPump, 62, 62, 'pump')
const ScrewPumpNode = symbolIconNode(ScrewPump, 76, 50, 'pump')
const VacuumPumpNode = symbolIconNode(VacuumPump, 76, 56, 'pump')
const TurbineNode = symbolIconNode(Turbine, 90, 64, 'compressor')
const SteamTurbineNode = symbolIconNode(SteamTurbine, 90, 64, 'compressor')
const GasTurbineNode = symbolIconNode(GasTurbine, 90, 64, 'compressor')
const ElectricMotorNode = symbolIconNode(ElectricMotor, 76, 56, 'pump')
const GearboxNode = symbolIconNode(Gearbox, 76, 56, 'pump')
const CentrifugalBlowerNode = symbolIconNode(CentrifugalBlower, 76, 76, 'compressor')
const RootsBlowerNode = symbolIconNode(RootsBlower, 76, 56, 'compressor')

// ── Electrical nodes ────────────────────────────────────────────────────────
const MotorNode = symbolIconNode(Motor, 64, 64, 'motor')
const HvMotorNode = symbolIconNode(HighVoltageMotor, 64, 64, 'motor')
const LvMotorNode = symbolIconNode(LowVoltageMotor, 64, 64, 'motor')
const VfdNode = symbolIconNode(VFD, 64, 64, 'motor')
const McmNode = symbolIconNode(MCC, 64, 64, 'motor')
const GeneratorNode = symbolIconNode(Generator, 64, 70, 'motor')
const DieselGeneratorNode = symbolIconNode(DieselGenerator, 64, 70, 'motor')
const TransformerNode = symbolIconNode(Transformer, 64, 64, 'motor')
const UpsNode = symbolIconNode(UPS, 64, 64, 'motor')
const BatteryBankNode = symbolIconNode(BatteryBank, 60, 56, 'motor')
const SwitchboardNode = symbolIconNode(Switchboard, 64, 64, 'motor')
const DistributionPanelNode = symbolIconNode(DistributionPanel, 64, 64, 'motor')
const JunctionBoxNode = symbolIconNode(JunctionBox, 60, 56, 'motor')
const TerminalBoxNode = symbolIconNode(TerminalBox, 60, 56, 'motor')
const ControlPanelNode = symbolIconNode(ControlPanel, 64, 64, 'motor')
const LocalControlStationNode = symbolIconNode(LocalControlStation, 64, 64, 'motor')
const DisconnectSwitchNode = symbolIconNode(DisconnectSwitch, 44, 64, 'motor')
const CircuitBreakerNode = symbolIconNode(CircuitBreaker, 44, 64, 'motor')
const FuseNode = symbolIconNode(Fuse, 44, 64, 'motor')
const GroundNode = symbolIconNode(Ground, 56, 60, 'motor')
const LightningProtectionNode = symbolIconNode(LightningProtection, 56, 60, 'motor')
const CableTrayNode = symbolIconNode(CableTray, 64, 40, 'motor')
const CableJunctionNode = symbolIconNode(CableJunction, 64, 56, 'motor')
const LightingFixtureNode = symbolIconNode(LightingFixture, 64, 64, 'motor')
const EmergencyLightingNode = symbolIconNode(EmergencyLighting, 64, 64, 'motor')

// ── Utilities nodes ─────────────────────────────────────────────────────────
const SteamTrapNode = symbolIconNode(SteamTrap, 60, 40, 'steam_trap')
const SteamSeparatorNode = symbolIconNode(SteamSeparator, 60, 66, 'steam_trap')
const SteamDrumNode = symbolIconNode(SteamDrum, 90, 60, 'steam_trap')
const SteamHeaderNode = symbolIconNode(SteamHeader, 64, 48, 'steam_trap')
const UtilityHeaderNode = symbolIconNode(UtilityHeader, 64, 48, 'steam_trap')

// Utility service line — one shared shape (per ISA convention, services
// differ by tag/line-code, not by icon) parameterized per kind with its
// real service code + ISA line-type dash pattern.
const UTIL_SERVICE: Record<string, { code: string; lineStyle: string }> = {
  util_cw: { code: 'CW', lineStyle: 'solid' },
  util_chw: { code: 'CHW', lineStyle: 'dashed' },
  util_bfw: { code: 'BFW', lineStyle: 'solid' },
  util_cr: { code: 'CR', lineStyle: 'dashed' },
  util_hw: { code: 'HW', lineStyle: 'solid' },
  util_ng: { code: 'NG', lineStyle: 'dash-dot' },
  util_fg: { code: 'FG', lineStyle: 'dash-dot' },
  util_ia: { code: 'IA', lineStyle: 'dash-dot-dot' },
  util_pa: { code: 'PA', lineStyle: 'dash-dot-dot' },
  util_n2: { code: 'N2', lineStyle: 'dash-dot' },
  util_o2: { code: 'O2', lineStyle: 'dash-dot' },
  util_h2: { code: 'H2', lineStyle: 'dash-dot' },
  util_ca: { code: 'CA', lineStyle: 'dash-dot-dot' },
  util_vac: { code: 'VAC', lineStyle: 'dashed' },
  util_caustic: { code: 'CAU', lineStyle: 'solid' },
  util_acid: { code: 'ACD', lineStyle: 'solid' },
  util_dmw: { code: 'DMW', lineStyle: 'solid' },
  util_pw: { code: 'PW', lineStyle: 'solid' },
  util_potable: { code: 'POT', lineStyle: 'solid' },
}

function UtilityLineNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const kind = String(data.kind ?? '')
  const lbl = String(data.label ?? '')
  const { border } = equipColors('steam_trap')
  const svc = UTIL_SERVICE[kind]
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <AllHandles />
      <UtilityLine width={64} height={40} stroke={border} strokeWidth={STROKE.signal}
        selected={selected} serviceCode={svc?.code ?? ''}
        lineStyle={(svc?.lineStyle ?? 'solid') as 'solid' | 'dashed' | 'dash-dot' | 'dash-dot-dot'} />
      <ValveLabel text={lbl} color={border} />
    </div>
  )
}

// ── Fire & safety nodes ─────────────────────────────────────────────────────
const FireWaterPumpNode = symbolIconNode(FireWaterPump, 62, 62, 'fire_water_pump')
const JockeyPumpNode = symbolIconNode(JockeyPump, 62, 62, 'fire_water_pump')
const DieselFirePumpNode = symbolIconNode(DieselFirePump, 62, 62, 'fire_water_pump')
const DelugeValveNode = symbolIconNode(DelugeValve, 64, 56, 'fire_water_pump')
const FireHydrantNode = symbolIconNode(FireHydrant, 64, 56, 'fire_water_pump')
const SprinklerHeadNode = symbolIconNode(SprinklerHead, 64, 64, 'fire_water_pump')
const WaterMonitorNode = symbolIconNode(WaterMonitor, 64, 64, 'fire_water_pump')
const FoamMonitorNode = symbolIconNode(FoamMonitor, 64, 64, 'fire_water_pump')
const SmokeDetectorNode = symbolIconNode(SmokeDetector, 60, 48, 'fire_water_pump')
const HeatDetectorNode = symbolIconNode(HeatDetector, 60, 48, 'fire_water_pump')
const FlameDetectorNode = symbolIconNode(FlameDetector, 60, 56, 'fire_water_pump')
const GasDetectorNode = symbolIconNode(GasDetector, 60, 56, 'fire_water_pump')
const ToxicGasDetectorNode = symbolIconNode(ToxicGasDetector, 60, 56, 'fire_water_pump')
const EmergencyShowerNode = symbolIconNode(EmergencyShower, 64, 64, 'fire_water_pump')
const EyeWashStationNode = symbolIconNode(EyeWashStation, 64, 64, 'fire_water_pump')
const SafetyShowerNode = symbolIconNode(SafetyShower, 64, 64, 'fire_water_pump')
const EscapeBreathingApparatusNode = symbolIconNode(EscapeBreathingApparatus, 60, 60, 'fire_water_pump')
const FireExtinguisherNode = symbolIconNode(FireExtinguisher, 60, 60, 'fire_water_pump')
const FireAlarmNode = symbolIconNode(FireAlarm, 60, 60, 'fire_water_pump')
const ManualCallPointNode = symbolIconNode(ManualCallPoint, 60, 60, 'fire_water_pump')
const EmergencyStopNode = symbolIconNode(EmergencyStop, 60, 60, 'fire_water_pump')
const FlameArrestorNode = symbolIconNode(FlameArrestor, 64, 56, 'fire_water_pump')
const ExplosionVentNode = symbolIconNode(ExplosionVent, 64, 64, 'fire_water_pump')
const BlastReliefPanelNode = symbolIconNode(BlastReliefPanel, 64, 64, 'fire_water_pump')
const PressureVentNode = symbolIconNode(PressureVent, 60, 64, 'fire_water_pump')
const EmergencyVentNode = symbolIconNode(EmergencyVent, 60, 64, 'fire_water_pump')

// ── Ejector / venturi (80×50) ─────────────────────────────────────────────────
function EjectorNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = equipColors('pump')
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 80 50" xmlns="http://www.w3.org/2000/svg">
        <line x1="40" y1="2" x2="40" y2="14" stroke={border} strokeWidth={STROKE.signal} />
        <polygon points="4,6 36,22 36,28 4,44" fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.signal} />
        <polygon points="44,22 76,8 76,42 44,28" fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.signal} />
        <line x1="36" y1="22" x2="44" y2="22" stroke={border} strokeWidth={STROKE.signal} />
        <line x1="36" y1="28" x2="44" y2="28" stroke={border} strokeWidth={STROKE.signal} />
        <text className="isa-tag" x="40" y="42" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 72, 9)} fontWeight="700" fill={text}>{formatTag(lbl)}</text>
      </svg>
    </div>
  )
}

// ── Reactor / heat-exchanger nodes ─────────────────────────────────────────────
// These reuse the pid-symbols icon components directly instead of redrawing
// each shape at canvas scale: SVG's default preserveAspectRatio ("xMidYMid
// meet") scales the icon's square viewBox to fit any node box without
// distortion, so one component serves both the palette preview and the
// placed-node symbol. Tag label reuses the same below-shape ValveLabel
// convention already used for valves/instruments in this file.
type SymbolIcon = (props: { width?: number; height?: number; stroke?: string; strokeWidth?: number; selected?: boolean }) => ReactElement

// `w`/`h` are unused for pixel sizing — kept only so every call site still
// documents each icon's real proportions at a glance. The rendered icon
// always fills 100% of the node's actual box (itself sized by getNodeSize
// on the React Flow node), and the icon's own square viewBox + default
// preserveAspectRatio letterboxes into that box automatically — same
// pattern every other inline <svg width="100%" height="100%"> node in this
// file already uses. This is what makes resizing getNodeSize() alone
// enough to resize what's drawn, with no second hardcoded number to drift
// out of sync.
function symbolIconNode(Icon: SymbolIcon, _w: number, _h: number, colorKind: string) {
  return function IconNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
    const lbl = String(data.label ?? '')
    const { border, text } = equipColors(colorKind)
    return (
      <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <AllHandles />
        <Icon width={'100%' as unknown as number} height={'100%' as unknown as number}
          stroke={border} strokeWidth={STROKE.symbol} selected={selected} />
        <ValveLabel text={lbl} color={text} />
      </div>
    )
  }
}

const CstrNode = symbolIconNode(CSTR, 94, 126, 'reactor')
const PfrNode = symbolIconNode(PFR, 130, 88, 'reactor')
const FixedBedNode = symbolIconNode(FixedBed, 94, 126, 'reactor')
const FluidizedBedNode = symbolIconNode(FluidizedBed, 94, 126, 'reactor')
const BatchReactorNode = symbolIconNode(BatchReactor, 94, 126, 'reactor')

const ShellTubeNode = symbolIconNode(ShellTube, 96, 64, 'heat_exchanger')
const PlateHxNode = symbolIconNode(PlateHeatExchanger, 76, 76, 'heat_exchanger')
const CondenserNode = symbolIconNode(Condenser, 76, 76, 'heat_exchanger')
const ReboilerNode = symbolIconNode(Reboiler, 76, 76, 'heat_exchanger')
const AirCoolerNode = symbolIconNode(AirCooler, 96, 60, 'heat_exchanger')
const FiredHeaterNode = symbolIconNode(FiredHeater, 76, 92, 'heat_exchanger')
const BoilerNode = symbolIconNode(Boiler, 76, 106, 'heat_exchanger')

const SpiralHXNode = symbolIconNode(SpiralHX, 76, 76, 'heat_exchanger')
const DoublePipeHXNode = symbolIconNode(DoublePipeHX, 76, 50, 'heat_exchanger')
const PlateFrameHXNode = symbolIconNode(PlateFrameHX, 76, 76, 'heat_exchanger')
const HairpinHXNode = symbolIconNode(HairpinHX, 76, 76, 'heat_exchanger')
const EvaporatorNode = symbolIconNode(Evaporator, 76, 92, 'heat_exchanger')
const EconomizerNode = symbolIconNode(Economizer, 76, 92, 'heat_exchanger')
const SuperheaterNode = symbolIconNode(Superheater, 76, 76, 'heat_exchanger')
const WasteHeatBoilerNode = symbolIconNode(WasteHeatBoiler, 76, 76, 'heat_exchanger')

// Roof-variant closures over AtmosphericTank — each just fixes the `roof`
// prop so symbolIconNode can treat them like any other single-shape icon.
const ConeRoofTankIcon: SymbolIcon = p => <AtmosphericTank {...p} roof="cone" />
const DomeRoofTankIcon: SymbolIcon = p => <AtmosphericTank {...p} roof="dome" />
const FloatingRoofTankIcon: SymbolIcon = p => <AtmosphericTank {...p} roof="floating" />
const IfrTankIcon: SymbolIcon = p => <AtmosphericTank {...p} roof="internal_floating" />

const SphereVesselNode = symbolIconNode(SphericalVessel, 96, 96, 'vessel')
const HortonSphereNode = symbolIconNode(HortonSphere, 96, 110, 'vessel')
const BulletTankNode = symbolIconNode(BulletTank, 130, 88, 'vessel')
const ConeRoofTankNode = symbolIconNode(ConeRoofTankIcon, 82, 98, 'vessel')
const DomeRoofTankNode = symbolIconNode(DomeRoofTankIcon, 82, 98, 'vessel')
const FloatingRoofTankNode = symbolIconNode(FloatingRoofTankIcon, 82, 98, 'vessel')
const IfrTankNode = symbolIconNode(IfrTankIcon, 82, 98, 'vessel')
const CryoTankNode = symbolIconNode(CryogenicTank, 82, 98, 'vessel')
const DoubleWallTankNode = symbolIconNode(DoubleWallTank, 82, 98, 'vessel')

const VacuumTowerNode = symbolIconNode(VacuumTower, 62, 152, 'column')
const ReactorColumnNode = symbolIconNode(ReactorColumn, 62, 152, 'column')

const BubbleColumnReactorNode = symbolIconNode(BubbleColumnReactor, 94, 126, 'reactor')
const LoopReactorNode = symbolIconNode(LoopReactor, 110, 80, 'reactor')
const SlurryReactorNode = symbolIconNode(SlurryReactor, 94, 126, 'reactor')
const MembraneReactorNode = symbolIconNode(MembraneReactor, 94, 126, 'reactor')
const TrickleBedReactorNode = symbolIconNode(TrickleBedReactor, 94, 126, 'reactor')
const CatalyticCrackerNode = symbolIconNode(CatalyticCracker, 90, 110, 'reactor')
const FurnaceReactorNode = symbolIconNode(FurnaceReactor, 76, 92, 'reactor')

// ── Vessel horizontal (cylinder + dished heads + saddles, 140×90) ─────────────
function VesselNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const detail = String(data.kind_detail ?? data.kind ?? '').replace(/_/g, ' ')
  const { bg, border, text } = equipColors('vessel')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg">
        <g fill={bg} stroke={stroke} strokeWidth={STROKE.symbol} strokeLinejoin="round">
          <HorizontalBody x={40} y={15} w={80} h={60} />
        </g>
        <g stroke={stroke} strokeWidth={STROKE.symbol}>
          <line x1="80" y1="15" x2="80" y2="4" />
          <line x1="0" y1="45" x2="10" y2="45" />
        </g>
        <text className="isa-tag" x="80" y="45" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 152, 13)} fontWeight="700" fill="white">{formatTag(lbl)}</text>
        <text className="isa-detail" x="80" y="63" textAnchor="middle" dominantBaseline="central"
          {...fitTag(detail, 152, 9)} fill={text}>{detail}</text>
      </svg>
    </div>
  )
}

// ── Vessel vertical (cylinder + dished heads + nozzles, 80×130) — ISA vertical separator ──
function VesselVerticalNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const detail = String(data.kind_detail ?? data.kind ?? '').replace(/_/g, ' ')
  const { bg, border, text } = equipColors('vessel')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 80 130" xmlns="http://www.w3.org/2000/svg">
        <g fill={bg} stroke={stroke} strokeWidth={STROKE.symbol}>
          <VerticalBody x={10} y={18} w={60} h={94} capRy={10} />
        </g>
        <g stroke={stroke} strokeWidth={STROKE.symbol}>
          <line x1="40" y1="8" x2="40" y2="2" />
          <line x1="40" y1="122" x2="40" y2="128" />
          <line x1="10" y1="40" x2="2" y2="40" />
          <line x1="70" y1="90" x2="78" y2="90" />
        </g>
        <text className="isa-tag" x="40" y="60" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 72, 13)} fontWeight="700" fill="white">{formatTag(lbl)}</text>
        <text className="isa-detail" x="40" y="80" textAnchor="middle" dominantBaseline="central"
          {...fitTag(detail, 72, 8)} fill={text}>{detail}</text>
      </svg>
    </div>
  )
}

// ── Flash drum (vertical vessel, single side feed inlet, 80×130) ──────────────
function FlashDrumNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const detail = String(data.kind_detail ?? data.kind ?? '').replace(/_/g, ' ')
  const { bg, border, text } = equipColors('vessel')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 80 130" xmlns="http://www.w3.org/2000/svg">
        <g fill={bg} stroke={stroke} strokeWidth={STROKE.symbol}>
          <VerticalBody x={10} y={18} w={60} h={94} capRy={10} />
        </g>
        <g stroke={stroke} strokeWidth={STROKE.symbol}>
          <line x1="40" y1="8" x2="40" y2="2" />
          <line x1="40" y1="122" x2="40" y2="128" />
          <line x1="10" y1="60" x2="2" y2="60" />
        </g>
        <text className="isa-tag" x="40" y="45" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 72, 13)} fontWeight="700" fill="white">{formatTag(lbl)}</text>
        <text className="isa-detail" x="40" y="95" textAnchor="middle" dominantBaseline="central"
          {...fitTag(detail, 72, 8)} fill={text}>{detail}</text>
      </svg>
    </div>
  )
}

// ── Accumulator (vertical vessel, top/bottom nozzles only + interface line, 80×130) ──
function AccumulatorNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const detail = String(data.kind_detail ?? data.kind ?? '').replace(/_/g, ' ')
  const { bg, border, text } = equipColors('vessel')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 80 130" xmlns="http://www.w3.org/2000/svg">
        <g fill={bg} stroke={stroke} strokeWidth={STROKE.symbol}>
          <VerticalBody x={10} y={18} w={60} h={94} capRy={10} />
        </g>
        <g stroke={stroke} strokeWidth={STROKE.symbol}>
          <line x1="40" y1="8" x2="40" y2="2" />
          <line x1="40" y1="122" x2="40" y2="128" />
        </g>
        <line x1="14" y1="70" x2="66" y2="70" stroke={border} strokeWidth="1" strokeDasharray="3 2" opacity="0.7" />
        <text className="isa-tag" x="40" y="45" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 72, 13)} fontWeight="700" fill="white">{formatTag(lbl)}</text>
        <text className="isa-detail" x="40" y="95" textAnchor="middle" dominantBaseline="central"
          {...fitTag(detail, 72, 8)} fill={text}>{detail}</text>
      </svg>
    </div>
  )
}

// KO drum — ISA convention: same outline as the horizontal vessel, distinguished
// only by tag/metadata, not geometry.
const KnockoutDrumNode = VesselNode

// ── Hopper / silo (cylinder + conical discharge, 82×110) ──────────────────────
function HopperSiloNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const detail = String(data.kind_detail ?? data.kind ?? '').replace(/_/g, ' ')
  const { bg, border, text } = equipColors('vessel')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 82 110" xmlns="http://www.w3.org/2000/svg">
        <path d="M 12,8 L 70,8 L 70,60 L 41,100 L 12,60 Z"
          fill={bg} stroke={stroke} strokeWidth={STROKE.symbol} strokeLinejoin="round" />
        <line x1="41" y1="100" x2="41" y2="108" stroke={stroke} strokeWidth={STROKE.symbol} />
        <text className="isa-tag" x="41" y="34" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 74, 12)} fontWeight="700" fill="white">{formatTag(lbl)}</text>
        <text className="isa-detail" x="41" y="50" textAnchor="middle" dominantBaseline="central"
          {...fitTag(detail, 74, 8)} fill={text}>{detail}</text>
      </svg>
    </div>
  )
}

// ── Atmospheric storage tank (flat-bottomed cylinder, 110×130) ────────────────
// Distinct from a pressure vessel: flat bottom (sits on grade), shallow domed
// top. ISA-5.1 storage-tank convention.
function TankNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const detail = String(data.kind_detail ?? data.kind ?? '').replace(/_/g, ' ')
  const { bg, border, text } = equipColors('vessel')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 110 130" xmlns="http://www.w3.org/2000/svg">
        {/* Cylindrical body with a flat bottom */}
        <path d="M 12,26 L 12,118 L 98,118 L 98,26"
          fill={bg} stroke={stroke} strokeWidth={STROKE.symbol} strokeLinejoin="round" />
        {/* Shallow domed roof */}
        <path d="M 12,26 Q 55,8 98,26" fill={bg} stroke={stroke} strokeWidth={STROKE.symbol} />
        {/* Grade line under the flat base */}
        <line x1="4" y1="118" x2="106" y2="118" stroke={stroke} strokeWidth={STROKE.symbol} />
        <text className="isa-tag" x="55" y="64" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 102, 13)} fontWeight="700" fill="white">{formatTag(lbl)}</text>
        <text className="isa-detail" x="55" y="84" textAnchor="middle" dominantBaseline="central"
          {...fitTag(detail, 102, 8)} fill={text}>{detail}</text>
      </svg>
    </div>
  )
}

const FilterNode = symbolIconNode(FilterIcon, 70, 52, 'filter')
const CycloneNode = symbolIconNode(Cyclone, 64, 64, 'filter')
const CentrifugeNode = symbolIconNode(Centrifuge, 68, 60, 'filter')
const MembraneNode = symbolIconNode(Membrane, 70, 52, 'filter')
const DecanterNode = symbolIconNode(Decanter, 90, 60, 'filter')
const ClarifierNode = symbolIconNode(Clarifier, 76, 76, 'filter')
const ThreePhaseSepNode = symbolIconNode(ThreePhaseSeparator, 90, 60, 'filter')
const OilWaterSepNode = symbolIconNode(OilWaterSeparator, 90, 60, 'filter')
const EspNode = symbolIconNode(ElectrostaticPrecipitator, 76, 76, 'filter')
const DemisterNode = symbolIconNode(Demister, 70, 76, 'filter')
const CoalescerNode = symbolIconNode(Coalescer, 70, 76, 'filter')
const SettlingTankNode = symbolIconNode(SettlingTank, 76, 76, 'filter')

// ── Column shell (cylinder + dished heads + nozzles, 60×160) — shared by the
// tray/packed/absorber/scrubber/stripper towers below; only the internals
// and side-nozzle placement differ per equipment type.
function ColumnShell({ children, border, bg, stroke, sideNozzleY = [] }: {
  children: ReactNode; border: string; bg: string; stroke: string
  sideNozzleY?: { y: number; side: 'left' | 'right' }[]
}) {
  return (
    <g>
      <g fill={bg} stroke={stroke} strokeWidth={STROKE.symbol}>
        <VerticalBody x={6} y={14} w={48} h={128} capRy={10} />
      </g>
      <g stroke={stroke} strokeWidth={STROKE.symbol}>
        <line x1="30" y1="4" x2="30" y2="0" />
        <line x1="30" y1="152" x2="30" y2="158" />
        {sideNozzleY.map(({ y, side }) => side === 'left'
          ? <line key={`${side}${y}`} x1="6" y1={y} x2="0" y2={y} />
          : <line key={`${side}${y}`} x1="54" y1={y} x2="60" y2={y} />)}
      </g>
      <g stroke={border} strokeWidth="1" opacity="0.7">{children}</g>
    </g>
  )
}

function TrayLines() {
  return <>{[28, 50, 72, 94, 116, 138].map(y =>
    <line key={y} x1="10" y1={y} x2="50" y2={y} strokeDasharray="4 3" />)}</>
}

function PackingMesh() {
  const rows = [24, 46, 68, 90, 112, 134]
  return <>{rows.slice(0, -1).map((y, i) => {
    const y2 = rows[i + 1]
    return <g key={y}>
      <line x1="10" y1={y} x2="50" y2={y2} />
      <line x1="50" y1={y} x2="10" y2={y2} />
    </g>
  })}</>
}

// ── Tray column (trays + feed/product side nozzles) ───────────────────────────
function TrayColumnNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = equipColors('column')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 60 160" xmlns="http://www.w3.org/2000/svg">
        <ColumnShell border={border} bg={bg} stroke={stroke}
          sideNozzleY={[{ y: 40, side: 'left' }, { y: 100, side: 'right' }]}>
          <TrayLines />
        </ColumnShell>
        <text className="isa-tag" x="30" y="18" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 52, 12)} fontWeight="700" fill={text}>{formatTag(lbl)}</text>
      </svg>
    </div>
  )
}

// ── Packed column (diamond-mesh packing, no trays) ────────────────────────────
function PackedColumnNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = equipColors('column')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 60 160" xmlns="http://www.w3.org/2000/svg">
        <ColumnShell border={border} bg={bg} stroke={stroke}
          sideNozzleY={[{ y: 70, side: 'left' }]}>
          <PackingMesh />
        </ColumnShell>
        <text className="isa-tag" x="30" y="18" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 52, 12)} fontWeight="700" fill={text}>{formatTag(lbl)}</text>
      </svg>
    </div>
  )
}

// ── Absorber (packed internals, gas-treating nozzle set) ──────────────────────
function AbsorberNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = equipColors('column')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 60 160" xmlns="http://www.w3.org/2000/svg">
        <ColumnShell border={border} bg={bg} stroke={stroke}
          sideNozzleY={[{ y: 28, side: 'right' }, { y: 70, side: 'left' }, { y: 120, side: 'right' }]}>
          <PackingMesh />
        </ColumnShell>
        <text className="isa-tag" x="30" y="18" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 52, 12)} fontWeight="700" fill={text}>{formatTag(lbl)}</text>
      </svg>
    </div>
  )
}

// ── Scrubber (spray nozzles + mist eliminator band + bottom sump) ─────────────
function ScrubberNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = equipColors('column')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 60 160" xmlns="http://www.w3.org/2000/svg">
        <ColumnShell border={border} bg={bg} stroke={stroke}
          sideNozzleY={[{ y: 130, side: 'left' }]}>
          {/* Spray nozzles */}
          <path d="M 20,28 L 24,36 M 24,36 L 20,44 M 24,36 L 28,44" />
          <path d="M 30,28 L 30,44" />
          <path d="M 40,28 L 36,36 M 36,36 L 40,44 M 36,36 L 32,44" />
          {/* Mist eliminator */}
          <line x1="10" y1="52" x2="50" y2="52" strokeDasharray="2 3" />
          <line x1="10" y1="58" x2="50" y2="58" strokeDasharray="2 3" />
        </ColumnShell>
        <text className="isa-tag" x="30" y="18" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 52, 12)} fontWeight="700" fill={text}>{formatTag(lbl)}</text>
      </svg>
    </div>
  )
}

// ── Stripper (tray internals + low-side steam inlet) ──────────────────────────
function StripperNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = equipColors('column')
  const stroke = selected ? Theme.selection : border
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 60 160" xmlns="http://www.w3.org/2000/svg">
        <ColumnShell border={border} bg={bg} stroke={stroke}
          sideNozzleY={[{ y: 40, side: 'left' }, { y: 140, side: 'right' }]}>
          <TrayLines />
        </ColumnShell>
        <text className="isa-tag" x="30" y="18" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 52, 12)} fontWeight="700" fill={text}>{formatTag(lbl)}</text>
      </svg>
    </div>
  )
}

// ── Vendor package (dashed boundary rect, 160×80) ─────────────────────────────
function VendorPackageNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const isSolid = data.kind === 'package'
  const { border, text } = equipColors('vessel')
  const caption = isSolid ? 'PACKAGE' : 'VENDOR PACKAGE'
  // This <svg> has NO viewBox, so user units are real pixels — fit the labels to
  // the node's actual width (offW, set by CanvasScreen) rather than a fixed box.
  const inner = Math.max(40, Number(data.offW ?? 160) - 20)
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        {/* Boundary — ISA vendor package / equipment box */}
        <rect x="2" y="2" rx="4"
          style={{ width: 'calc(100% - 4px)', height: 'calc(100% - 4px)' }}
          fill="transparent"
          stroke={selected ? Theme.selection : border}
          strokeWidth={STROKE.symbol} strokeDasharray={isSolid ? 'none' : '8 8'} />
        <text className="isa-tag" x="50%" y="20" textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), inner, 14)} fontWeight="700" fill={text}>{formatTag(lbl)}</text>
        {/* Bottom-left caption — ISA convention for a vendor-supplied skid boundary */}
        <text className="isa-detail" x="10" y="100%" dy="-8" textAnchor="start"
          {...fitTag(caption, inner, 9)} fontWeight="700" letterSpacing="0.5" fill={text} opacity="0.85">
          {caption}
        </text>
      </svg>
    </div>
  )
}

// ── Off-page connector (directional pentagon, dynamic width) ──────────────────
// Points RIGHT for flow exiting to the right, LEFT for flow exiting to the left,
// so inlets and outlets read naturally. Width scales with the label.
function OffPageNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const cleaned = lbl.replace(/^off_page_?/i, '') || lbl
  // Prefer the line/stream number (e.g. 157-2-145) as the connector tag —
  // matches what the original drawing shows in the connector box. The full
  // text stays available via the hover tooltip.
  const lineNo = cleaned.match(/\d{2,}-\d+-\d+(?:-\S+)?/)?.[0]
  const disp = lineNo ?? cleaned
  const d = data as Record<string, unknown>
  const W = Number(d.offW ?? 120)
  const H = 40
  const PT = 14   // chevron point depth
  const pointsRight = String(d.offDir ?? 'right') !== 'left'
  const stroke = selected ? Theme.selection : OFFPAGE_C.border

  // Pentagon pointing right or left
  const poly = pointsRight
    ? `2,2 ${W - PT},2 ${W - 2},${H / 2} ${W - PT},${H - 2} 2,${H - 2}`
    : `${PT},2 ${W - 2},2 ${W - 2},${H - 2} ${PT},${H - 2} 2,${H / 2}`

  // Text fits inside the flat region (away from the point)
  const avail = W - PT - 12
  const maxChars = Math.max(4, Math.floor(avail / 5.6))
  const shown = disp.length > maxChars ? disp.slice(0, maxChars - 1) + '…' : disp
  const textCx = pointsRight ? (W - PT) / 2 + 2 : PT + (W - PT) / 2

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }} title={cleaned}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
        xmlns="http://www.w3.org/2000/svg">
        <polygon points={poly}
          fill={OFFPAGE_C.bg} stroke={stroke}
          strokeWidth="1" strokeDasharray="3 2" />
        <text className="isa-tag" x={textCx} y={H / 2} textAnchor="middle" dominantBaseline="central"
          fontSize="9" fill={OFFPAGE_C.text}>{shown}</text>
      </svg>
    </div>
  )
}

// ── Default equipment (rounded rect, 120×60) ──────────────────────────────────
function EquipNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const kind = String(data.kind ?? '')
  const detail = String(data.kind_detail ?? kind).replace(/_/g, ' ')
  const { bg, border, text } = equipColors(kind)
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <AllHandles />
      <svg width="100%" height="100%" viewBox="0 0 120 60" xmlns="http://www.w3.org/2000/svg">
        <rect x="2" y="2" width="116" height="56" rx="6" fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.symbol} />
        <text className="isa-tag" x="60" y={detail && detail !== lbl ? '22' : '30'} textAnchor="middle" dominantBaseline="central"
          {...fitTag(formatTag(lbl), 112, 13)} fontWeight="700" fill="white">{formatTag(lbl)}</text>
        {detail && detail !== lbl && (
          <text className="isa-detail" x="60" y="42" textAnchor="middle" dominantBaseline="central"
            {...fitTag(detail, 112, 9)} fill={text}>{detail}</text>
        )}
      </svg>
    </div>
  )
}

// ── Area group background ─────────────────────────────────────────────────────
function AreaGroupNode({ data }: NodeProps<Node<ISANodeData>>) {
  const color = String((data as Record<string, unknown>).color ?? 'transparent')
  return (
    <div style={{
      width: '100%', height: '100%',
      background: color,
      border: '1px solid rgba(100,116,139,0.12)',
      borderRadius: 12,
      padding: '10px 16px',
      pointerEvents: 'none',
      userSelect: 'none',
    }}>
      <span style={{
        fontSize: 11, fontWeight: 700,
        color: 'rgba(148,163,184,0.45)',
        textTransform: 'uppercase',
        letterSpacing: '0.11em',
      }}>
        {String(data.label)}
      </span>
    </div>
  )
}

// ── Junction / T-junction node — tiny filled dot, no label ───────────────────
// Represents a branch point on a pipe segment where an instrument taps off.
// Visible as a small dot so edges physically branch at the correct pipe position.
function JunctionNode({ selected }: NodeProps<Node<ISANodeData>>) {
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <CenterHandles />
      {/* Small dot centred in the 16px hit body. pointer-events:none so a click
          lands on the node itself (selectable) instead of the SVG. */}
      <svg width="8" height="8" viewBox="0 0 8 8" style={{ pointerEvents: 'none' }} xmlns="http://www.w3.org/2000/svg">
        <circle cx="4" cy="4" r="3" fill={Theme.junction} stroke={selected ? Theme.selection : Theme.hover} strokeWidth="1" />
      </svg>
    </div>
  )
}

// ── Quick Connect — hydraulic style with check (ISA / ISO 1219) ────────────
function QuickConnectNode({ selected }: NodeProps<Node<ISANodeData>>) {
  const stroke = selected ? Theme.selection : Theme.processPipe
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <CenterHandles />
      <svg width="100%" height="100%" viewBox="0 0 32 24" overflow="visible" xmlns="http://www.w3.org/2000/svg">
        {/* Solid vertical rectangle (female socket) */}
        <rect x="4" y="-8" width="24" height="40" fill={stroke} />
      </svg>
    </div>
  )
}

// ── Thermocouple — thermowell probe with dashed capillary to bubble (ISA 5.1) ──
function ThermocoupleNode({ data, selected }: NodeProps<Node<ISANodeData>>) {
  const lbl = String(data.label ?? '')
  const { bg, border, text } = instrColors(lbl)
  const pipe = selected ? Theme.selection : Theme.processPipe

  // A thermocouple is typically drawn as a heavy dot or small thermowell rectangle
  // on the pipe, with a dashed capillary line connecting to the instrument bubble.
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <CenterHandles />
      <svg width="100%" height="100%" viewBox="0 0 44 44" xmlns="http://www.w3.org/2000/svg">
        {/* Thermowell / probe on the pipe at the bottom */}
        <circle cx="22" cy="38" r="4" fill={pipe} />
        {/* Dashed capillary line to the instrument bubble */}
        <line x1="22" y1="34" x2="22" y2="18" stroke={border} strokeWidth="1" strokeDasharray="3 2" />
        {/* Instrument bubble */}
        <circle cx="22" cy="12" r="11" fill={bg} stroke={selected ? Theme.selection : border} strokeWidth={STROKE.symbol} />
        <text className="isa-tag" x="22" y="12" textAnchor="middle" dominantBaseline="central"
          fontSize="7" fontWeight="800"
          fill={text} fontFamily="monospace,'Courier New'">{lbl || 'TE'}</text>
      </svg>
    </div>
  )
}

// ── Node type registry ────────────────────────────────────────────────────────
export const NODE_TYPES = {
  instrument: InstrumentNode,
  dcs_func: DcsFuncNode,
  sis_func: SisFuncNode,
  ctrl_controller: ControllerNode,
  ctrl_recorder: RecorderNode,
  ctrl_high_switch: HighSwitchNode,
  ctrl_low_switch: LowSwitchNode,
  ctrl_dcs: DcsCtrlNode,
  ctrl_plc: PlcCtrlNode,
  ctrl_sis: SisCtrlNode,
  mfm: MfmNode,
  td: TdNode,
  transducer: TransducerNode,
  alarm: AlarmNode,
  auto_man_selector: AutoManSelectorNode,
  level_glass: LevelGlassNode,
  valve: ValveNode,
  ball_valve: BallValveNode,
  butterfly_valve: ButterflyValveNode,
  gate_valve: GateValveNode,
  regulator: RegulatorNode,
  hand_valve: HandValveNode,
  check_valve: CheckValveNode,
  relief_valve: ReliefValveNode,
  rupture_disc: RuptureDiscNode,
  three_way_valve: ThreeWayValveNode,
  three_way_solenoid_valve: ThreeWaySolenoidValveNode,
  normally_closed_valve: NormallyClosedValveNode,
  plug_valve: PlugValveNode,
  pcv: PcvNode,
  back_pressure_regulator: BackPressureRegulatorNode,
  actuated_valve_general: ActuatedValveGeneralNode,
  mixing_tube: MixingTubeNode,
  micron_filter: MicronFilterNode,
  on_page_connector: OnPageConnectorNode,
  continuation_arrow: ContinuationArrowNode,
  orifice: OrificeNode,
  needle_valve: NeedleValveNode,
  solenoid_valve: SolenoidValveNode,
  pump_cent: CentrifugalPumpNode,
  pump_pd: PdPumpNode,
  mixer: MixerNode,
  ejector: EjectorNode,
  comp_cent: CentrifugalCompressorNode,
  comp_recip: ReciprocatingCompressorNode,
  blower: BlowerNode,
  gear_pump: GearPumpNode,
  screw_pump: ScrewPumpNode,
  diaphragm_pump: DiaphragmPumpNode,
  peristaltic_pump: PeristalticPumpNode,
  vacuum_pump: VacuumPumpNode,
  turbine: TurbineNode,
  steam_turbine: SteamTurbineNode,
  gas_turbine: GasTurbineNode,
  electric_motor: ElectricMotorNode,
  gearbox: GearboxNode,
  centrifugal_blower: CentrifugalBlowerNode,
  roots_blower: RootsBlowerNode,
  hx_shell_tube: ShellTubeNode,
  hx_plate: PlateHxNode,
  hx_condenser: CondenserNode,
  hx_reboiler: ReboilerNode,
  hx_air_cooler: AirCoolerNode,
  hx_fired_heater: FiredHeaterNode,
  hx_boiler: BoilerNode,
  spiral_hx: SpiralHXNode,
  double_pipe_hx: DoublePipeHXNode,
  plate_frame_hx: PlateFrameHXNode,
  hairpin_hx: HairpinHXNode,
  evaporator: EvaporatorNode,
  economizer: EconomizerNode,
  superheater: SuperheaterNode,
  waste_heat_boiler: WasteHeatBoilerNode,
  vessel_h: VesselNode,
  vessel_v: VesselVerticalNode,
  flash_drum: FlashDrumNode,
  knockout: KnockoutDrumNode,
  accumulator: AccumulatorNode,
  tank: TankNode,
  hopper: HopperSiloNode,
  sphere_vessel: SphereVesselNode,
  horton_sphere: HortonSphereNode,
  bullet_tank: BulletTankNode,
  tank_cone_roof: ConeRoofTankNode,
  tank_dome_roof: DomeRoofTankNode,
  tank_floating_roof: FloatingRoofTankNode,
  tank_ifr: IfrTankNode,
  cryo_tank: CryoTankNode,
  double_wall_tank: DoubleWallTankNode,
  cstr: CstrNode,
  pfr: PfrNode,
  fixed_bed: FixedBedNode,
  fluidized_bed: FluidizedBedNode,
  batch_reactor: BatchReactorNode,
  bubble_column_reactor: BubbleColumnReactorNode,
  loop_reactor: LoopReactorNode,
  slurry_reactor: SlurryReactorNode,
  membrane_reactor: MembraneReactorNode,
  trickle_bed_reactor: TrickleBedReactorNode,
  catalytic_cracker: CatalyticCrackerNode,
  furnace_reactor: FurnaceReactorNode,
  filter: FilterNode,
  cyclone: CycloneNode,
  centrifuge: CentrifugeNode,
  membrane: MembraneNode,
  decanter: DecanterNode,
  clarifier: ClarifierNode,
  three_phase_sep: ThreePhaseSepNode,
  oil_water_sep: OilWaterSepNode,
  esp: EspNode,
  demister: DemisterNode,
  coalescer: CoalescerNode,
  settling_tank: SettlingTankNode,
  motor: MotorNode,
  hv_motor: HvMotorNode,
  lv_motor: LvMotorNode,
  vfd: VfdNode,
  mcc: McmNode,
  generator: GeneratorNode,
  diesel_generator: DieselGeneratorNode,
  transformer: TransformerNode,
  ups: UpsNode,
  battery_bank: BatteryBankNode,
  switchboard: SwitchboardNode,
  distribution_panel: DistributionPanelNode,
  junction_box: JunctionBoxNode,
  terminal_box: TerminalBoxNode,
  control_panel: ControlPanelNode,
  local_control_station: LocalControlStationNode,
  disconnect_switch: DisconnectSwitchNode,
  circuit_breaker: CircuitBreakerNode,
  fuse: FuseNode,
  ground: GroundNode,
  lightning_protection: LightningProtectionNode,
  cable_tray: CableTrayNode,
  cable_junction: CableJunctionNode,
  lighting_fixture: LightingFixtureNode,
  emergency_lighting: EmergencyLightingNode,
  steam_trap: SteamTrapNode,
  steam_separator: SteamSeparatorNode,
  steam_drum: SteamDrumNode,
  steam_header: SteamHeaderNode,
  utility_header: UtilityHeaderNode,
  utility_line: UtilityLineNode,
  fire_water_pump: FireWaterPumpNode,
  jockey_pump: JockeyPumpNode,
  diesel_fire_pump: DieselFirePumpNode,
  deluge_valve: DelugeValveNode,
  fire_hydrant: FireHydrantNode,
  sprinkler_head: SprinklerHeadNode,
  water_monitor: WaterMonitorNode,
  foam_monitor: FoamMonitorNode,
  smoke_detector: SmokeDetectorNode,
  heat_detector: HeatDetectorNode,
  flame_detector: FlameDetectorNode,
  gas_detector: GasDetectorNode,
  toxic_gas_detector: ToxicGasDetectorNode,
  emergency_shower: EmergencyShowerNode,
  eye_wash_station: EyeWashStationNode,
  safety_shower: SafetyShowerNode,
  escape_breathing_apparatus: EscapeBreathingApparatusNode,
  fire_extinguisher: FireExtinguisherNode,
  fire_alarm: FireAlarmNode,
  manual_call_point: ManualCallPointNode,
  emergency_stop: EmergencyStopNode,
  flame_arrestor: FlameArrestorNode,
  explosion_vent: ExplosionVentNode,
  blast_relief_panel: BlastReliefPanelNode,
  pressure_vent: PressureVentNode,
  emergency_vent: EmergencyVentNode,
  tray_column: TrayColumnNode,
  packed_column: PackedColumnNode,
  absorber: AbsorberNode,
  scrubber: ScrubberNode,
  stripper: StripperNode,
  vacuum_tower: VacuumTowerNode,
  reactor_column: ReactorColumnNode,
  vendor_package: VendorPackageNode,
  offpage: OffPageNode,
  equipment: EquipNode,
  areagroup:     AreaGroupNode,
  junction:      JunctionNode,
  quick_connect: QuickConnectNode,
  thermocouple:  ThermocoupleNode,
}

// Shape-only (no tag text, no Handle) standalone versions of the bespoke
// inline-SVG *Node functions above — same <svg> geometry, minus <AllHandles/>
// and the label text (the export legend prints the label as a separate line,
// not baked into the icon). Exist purely so ICON_BY_TYPE below can give the
// legend the ACTUAL symbol for these types too, instead of a generic swatch.
type BareIconProps = { width?: number; height?: number; stroke?: string; strokeWidth?: number }

function TankIcon({ width = 20, height = 16, stroke = '#1d4ed8', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 110 130" xmlns="http://www.w3.org/2000/svg">
      <path d="M 12,26 L 12,118 L 98,118 L 98,26" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <path d="M 12,26 Q 55,8 98,26" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
      <line x1="4" y1="118" x2="106" y2="118" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}
function VesselHIcon({ width = 20, height = 16, stroke = '#1d4ed8', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round"><HorizontalBody x={40} y={15} w={80} h={60} /></g>
      <g stroke={stroke} strokeWidth={strokeWidth}>
        <line x1="80" y1="15" x2="80" y2="4" /><line x1="0" y1="45" x2="10" y2="45" />
      </g>
    </svg>
  )
}
function VesselVIcon({ width = 20, height = 16, stroke = '#1d4ed8', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 80 130" xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={stroke} strokeWidth={strokeWidth}><VerticalBody x={10} y={18} w={60} h={94} capRy={10} /></g>
      <g stroke={stroke} strokeWidth={strokeWidth}>
        <line x1="40" y1="8" x2="40" y2="2" /><line x1="40" y1="122" x2="40" y2="128" />
        <line x1="10" y1="40" x2="2" y2="40" /><line x1="70" y1="90" x2="78" y2="90" />
      </g>
    </svg>
  )
}
function FlashDrumIcon({ width = 20, height = 16, stroke = '#1d4ed8', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 80 130" xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={stroke} strokeWidth={strokeWidth}><VerticalBody x={10} y={18} w={60} h={94} capRy={10} /></g>
      <g stroke={stroke} strokeWidth={strokeWidth}>
        <line x1="40" y1="8" x2="40" y2="2" /><line x1="40" y1="122" x2="40" y2="128" />
        <line x1="10" y1="60" x2="2" y2="60" />
      </g>
    </svg>
  )
}
function AccumulatorIcon({ width = 20, height = 16, stroke = '#1d4ed8', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 80 130" xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={stroke} strokeWidth={strokeWidth}><VerticalBody x={10} y={18} w={60} h={94} capRy={10} /></g>
      <g stroke={stroke} strokeWidth={strokeWidth}>
        <line x1="40" y1="8" x2="40" y2="2" /><line x1="40" y1="122" x2="40" y2="128" />
      </g>
      <line x1="14" y1="70" x2="66" y2="70" stroke={stroke} strokeWidth="1" strokeDasharray="3 2" opacity="0.7" />
    </svg>
  )
}
function HopperIcon({ width = 20, height = 16, stroke = '#1d4ed8', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 82 110" xmlns="http://www.w3.org/2000/svg">
      <path d="M 12,8 L 70,8 L 70,60 L 41,100 L 12,60 Z" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <line x1="41" y1="100" x2="41" y2="108" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}
function InstrumentIcon({ width = 20, height = 16, stroke = '#7e22ce', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 50 50" xmlns="http://www.w3.org/2000/svg">
      <circle cx="25" cy="25" r="22" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}
function DcsFuncIcon({ width = 20, height = 16, stroke = '#7e22ce', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 50 50" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="3" width="44" height="44" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
      <circle cx="25" cy="25" r="22" fill="none" stroke={stroke} strokeWidth={Number(strokeWidth) * 0.75} opacity="0.6" />
    </svg>
  )
}
function SisFuncIcon({ width = 20, height = 16, stroke = '#7e22ce', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 50 50" xmlns="http://www.w3.org/2000/svg">
      <polygon points="25,2 48,25 25,48 2,25" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}
function LevelGlassIcon({ width = 20, height = 16, stroke = '#7e22ce', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 16 50" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="2" width="12" height="46" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}
function RegulatorIcon({ width = 20, height = 16, stroke = '#b45309', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 52 46" xmlns="http://www.w3.org/2000/svg">
      <line x1="26" y1="16" x2="26" y2="9" stroke={stroke} strokeWidth={strokeWidth} />
      <path d="M 16,9 A 10 7 0 0 1 36,9 Z" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
      <polygon points="2,16 2,44 26,30" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <polygon points="50,16 50,44 26,30" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
    </svg>
  )
}
function HandValveIcon({ width = 20, height = 16, stroke = '#b45309', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 44 32" xmlns="http://www.w3.org/2000/svg">
      <polygon points="2,8 2,30 22,19" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <polygon points="42,8 42,30 22,19" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <line x1="22" y1="19" x2="22" y2="4" stroke={stroke} strokeWidth={strokeWidth} />
      <line x1="16" y1="4" x2="28" y2="4" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}
function OrificeIcon({ width = 20, height = 16, stroke = '#b45309', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 36 32" xmlns="http://www.w3.org/2000/svg">
      <line x1="2" y1="16" x2="34" y2="16" stroke={stroke} strokeWidth={strokeWidth} />
      <line x1="18" y1="2" x2="18" y2="12" stroke={stroke} strokeWidth="3" strokeLinecap="square" />
      <line x1="18" y1="20" x2="18" y2="30" stroke={stroke} strokeWidth="3" strokeLinecap="square" />
    </svg>
  )
}
function NeedleValveIcon({ width = 20, height = 16, stroke = '#b45309', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 40 32" xmlns="http://www.w3.org/2000/svg">
      <polygon points="2,2 2,30 38,16" fill={stroke} stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <line x1="30" y1="8" x2="38" y2="24" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}
function SolenoidValveIcon({ width = 20, height = 16, stroke = '#b45309', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 52 40" xmlns="http://www.w3.org/2000/svg">
      <polygon points="2,14 2,38 26,26" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <polygon points="50,14 50,38 26,26" fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" />
      <rect x="16" y="2" width="20" height="10" fill="none" stroke={stroke} strokeWidth="1.2" />
      <line x1="26" y1="12" x2="26" y2="14" stroke={stroke} strokeWidth="1.2" />
    </svg>
  )
}
function EjectorIcon({ width = 20, height = 16, stroke = '#15803d', strokeWidth = 2 }: BareIconProps) {
  return (
    <svg width={width} height={height} viewBox="0 0 80 50" xmlns="http://www.w3.org/2000/svg">
      <line x1="40" y1="2" x2="40" y2="14" stroke={stroke} strokeWidth={strokeWidth} />
      <polygon points="4,6 36,22 36,28 4,44" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
      <polygon points="44,22 76,8 76,42 44,28" fill="none" stroke={stroke} strokeWidth={strokeWidth} />
      <line x1="36" y1="22" x2="44" y2="22" stroke={stroke} strokeWidth={strokeWidth} />
      <line x1="36" y1="28" x2="44" y2="28" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  )
}

// Bare (Handle-free, standalone-renderable) icon per node type, showing the
// ACTUAL symbol for each type present in a diagram instead of a generic
// placeholder shape.
//
// NOTE: its only consumer was the Canvas-capture SVG export
// (features/export/CanvasExportCapture.tsx), which was deleted when SVG export
// moved to the server-side ISA renderer. ICON_BY_TYPE and the bare-icon
// components above it now have no callers — kept for the moment rather than
// removed as a side effect of that change.
// Most entries reuse the same pid-symbols Icon component
// the canvas itself renders; the bespoke-inline-SVG types (vessel_h/tank/
// instrument/...) use the shape-only versions defined just above.
export const ICON_BY_TYPE: Record<string, (props: {
  width?: number; height?: number; stroke?: string; strokeWidth?: number
}) => ReactElement> = {
  valve: GlobeValve, ball_valve: BallValve, butterfly_valve: ButterflyValve,
  gate_valve: GateValve, check_valve: CheckValve, relief_valve: PSV,
  rupture_disc: RuptureDisc, three_way_valve: ThreeWayValve,
  three_way_solenoid_valve: ThreeWaySolenoidValve, normally_closed_valve: NormallyClosedValve,
  plug_valve: PlugValve, pcv: PressureRegulatorPCV,
  back_pressure_regulator: BackPressureRegulator, actuated_valve_general: ActuatedValveGeneral,

  ctrl_controller: Controller, ctrl_recorder: Recorder, ctrl_high_switch: HighSwitch,
  ctrl_low_switch: LowSwitch, ctrl_dcs: DCS, ctrl_plc: PLC, ctrl_sis: SIS,
  mfm: MassFlowMeter, td: DifferentialTemperature, transducer: Transducer,
  alarm: Alarm, auto_man_selector: AutoManualSelector,

  mixing_tube: MixingTube, micron_filter: MicronFilter,
  on_page_connector: OnPageConnector, continuation_arrow: ContinuationArrow,

  pump_cent: CentrifugalPump, pump_pd: PDPump, mixer: Mixer,
  comp_cent: CentrifugalCompressor, comp_recip: ReciprocatingCompressor, blower: Blower,
  gear_pump: GearPump, screw_pump: ScrewPump, diaphragm_pump: DiaphragmPump,
  peristaltic_pump: PeristalticPump, vacuum_pump: VacuumPump, turbine: Turbine,
  steam_turbine: SteamTurbine, gas_turbine: GasTurbine, electric_motor: ElectricMotor,
  gearbox: Gearbox, centrifugal_blower: CentrifugalBlower, roots_blower: RootsBlower,

  hx_shell_tube: ShellTube, hx_plate: PlateHeatExchanger, hx_condenser: Condenser,
  hx_reboiler: Reboiler, hx_air_cooler: AirCooler, hx_fired_heater: FiredHeater,
  hx_boiler: Boiler, spiral_hx: SpiralHX, double_pipe_hx: DoublePipeHX,
  plate_frame_hx: PlateFrameHX, hairpin_hx: HairpinHX, evaporator: Evaporator,
  economizer: Economizer, superheater: Superheater, waste_heat_boiler: WasteHeatBoiler,

  sphere_vessel: SphericalVessel, horton_sphere: HortonSphere, bullet_tank: BulletTank,
  tank_cone_roof: ConeRoofTankIcon, tank_dome_roof: DomeRoofTankIcon,
  tank_floating_roof: FloatingRoofTankIcon, tank_ifr: IfrTankIcon,
  cryo_tank: CryogenicTank, double_wall_tank: DoubleWallTank,

  cstr: CSTR, pfr: PFR, fixed_bed: FixedBed, fluidized_bed: FluidizedBed,
  batch_reactor: BatchReactor, bubble_column_reactor: BubbleColumnReactor,
  loop_reactor: LoopReactor, slurry_reactor: SlurryReactor,
  membrane_reactor: MembraneReactor, trickle_bed_reactor: TrickleBedReactor,
  catalytic_cracker: CatalyticCracker, furnace_reactor: FurnaceReactor,
  vacuum_tower: VacuumTower, reactor_column: ReactorColumn,

  filter: FilterIcon, cyclone: Cyclone, centrifuge: Centrifuge, membrane: Membrane,
  decanter: Decanter, clarifier: Clarifier, three_phase_sep: ThreePhaseSeparator,
  oil_water_sep: OilWaterSeparator, esp: ElectrostaticPrecipitator, demister: Demister,
  coalescer: Coalescer, settling_tank: SettlingTank,

  tank: TankIcon, vessel_h: VesselHIcon, vessel_v: VesselVIcon, flash_drum: FlashDrumIcon,
  knockout: VesselHIcon, accumulator: AccumulatorIcon, hopper: HopperIcon,
  instrument: InstrumentIcon, dcs_func: DcsFuncIcon, sis_func: SisFuncIcon, level_glass: LevelGlassIcon,
  regulator: RegulatorIcon, hand_valve: HandValveIcon, orifice: OrificeIcon,
  needle_valve: NeedleValveIcon, solenoid_valve: SolenoidValveIcon, ejector: EjectorIcon,
}

import { SymbolSvg } from './base'
import { BowtieBody, FlowLine } from './primitives'
import type { PidSymbolProps } from './types'

// Generic actuated valve — bowtie body with a plain flat-top actuator cap
// (no spring/diaphragm/solenoid detail), the ISA convention for "has a
// power actuator, type unspecified."
export default function ActuatedValveGeneral(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      <line x1="32" y1="16" x2="32" y2="8" />
      <path d="M 20,8 L 44,8 L 44,2 L 20,2 Z" />
    </SymbolSvg>
  )
}

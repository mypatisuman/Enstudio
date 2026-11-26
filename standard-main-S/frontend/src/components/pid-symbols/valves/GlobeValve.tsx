import { SymbolSvg } from './base'
import { BowtieBody, FlowLine, DiaphragmActuator } from './primitives'
import type { PidSymbolProps } from './types'

// Globe control valve (CV/FCV/LCV/PCV/TCV) — bowtie body, pneumatic
// diaphragm actuator, plug-and-seat mark at the throat where the two cones
// meet (the detail that separates a control valve from a plain hand valve).
export default function GlobeValve({ actuatorType = 'diaphragm', ...props }: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      {actuatorType !== 'none' && <DiaphragmActuator />}
      <line x1="32" y1="16" x2="32" y2="26" />
      <path d="M 27,26 L 32,32 L 37,26" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { BowtieBody, FlowLine, Handwheel, DiaphragmActuator } from './primitives'
import type { PidSymbolProps } from './types'

// Ball valve — bowtie body, ball-and-bore circle at the throat (the bore
// line rotates 90° between open/closed per valveState), manual handwheel by
// default or a diaphragm actuator for the actuated variant.
export default function BallValve({ actuatorType = 'manual', valveState = 'open', ...props }: PidSymbolProps) {
  const boreAngle = valveState === 'closed' ? 90 : 0
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      {actuatorType === 'diaphragm' ? <DiaphragmActuator /> : actuatorType !== 'none' && <Handwheel />}
      <circle cx="32" cy="32" r="9" />
      <line x1="24" y1="32" x2="40" y2="32" transform={`rotate(${boreAngle} 32 32)`} />
    </SymbolSvg>
  )
}

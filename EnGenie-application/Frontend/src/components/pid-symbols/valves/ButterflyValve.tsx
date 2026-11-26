import { SymbolSvg } from './base'
import { BowtieBody, FlowLine, Handwheel, DiaphragmActuator } from './primitives'
import type { PidSymbolProps } from './types'

// Butterfly valve — bowtie body with a large circular disc housing
// spanning the throat and a disc-edge line through it (wide when open,
// edge-on when closed per valveState) — distinct silhouette from the
// ball valve's small bore circle.
export default function ButterflyValve({ actuatorType = 'manual', valveState = 'open', ...props }: PidSymbolProps) {
  const discAngle = valveState === 'closed' ? 90 : 0
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      {actuatorType === 'diaphragm' ? <DiaphragmActuator /> : actuatorType !== 'none' && <Handwheel />}
      <circle cx="32" cy="32" r="14" />
      <line x1="32" y1="18" x2="32" y2="46" transform={`rotate(${discAngle} 32 32)`} />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { MachineCircle } from './primitives'
import type { PidSymbolProps } from './types'

// Low-voltage motor — motor circle with a single terminal tick (vs. the
// HV double tick), the standard single-line convention for LV connections.
export default function LowVoltageMotor(props: PidSymbolProps) {
  const color = props.stroke ?? '#F59E0B'
  return (
    <SymbolSvg {...props}>
      <MachineCircle letter="M" color={color} />
      <line x1="32" y1="8" x2="32" y2="4" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { MachineCircle } from './primitives'
import type { PidSymbolProps } from './types'

// High-voltage motor — motor circle plus the HV double-tick terminal marks
// used on single-line diagrams to flag a high-voltage connection.
export default function HighVoltageMotor(props: PidSymbolProps) {
  const color = props.stroke ?? '#F59E0B'
  return (
    <SymbolSvg {...props}>
      <MachineCircle letter="M" color={color} />
      <line x1="28" y1="8" x2="32" y2="4" />
      <line x1="36" y1="8" x2="32" y2="4" />
    </SymbolSvg>
  )
}

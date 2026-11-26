import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// 3-way solenoid valve — same three-port body as ThreeWayValve, with a
// solenoid actuator (square + diagonal coil line, the IEC electrical
// actuator convention) instead of a handwheel.
export default function ThreeWaySolenoidValve(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <polygon points="4,16 4,48 32,32" />
      <polygon points="60,16 60,48 32,32" />
      <polygon points="20,56 44,56 32,32" />
      <line x1="0" y1="32" x2="4" y2="32" />
      <line x1="60" y1="32" x2="64" y2="32" />
      <line x1="32" y1="56" x2="32" y2="62" />
      <line x1="32" y1="16" x2="32" y2="10" />
      <rect x="24" y="2" width="16" height="8" />
      <line x1="24" y1="2" x2="40" y2="10" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Pressure vent — weighted/spring-loaded vent cap on a stack (opens at a
// set pressure, closes after), distinct from EmergencyVent's plain open stack.
export default function PressureVent(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="24" y1="60" x2="24" y2="26" />
      <line x1="40" y1="60" x2="40" y2="26" />
      <path d="M 20,26 L 44,26 L 32,10 Z" />
      <path d="M 26,20 L 26,14 M 30,20 L 30,14 M 34,20 L 34,14 M 38,20 L 38,14" strokeDasharray="1 2" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Emergency vent — plain open stack (no weighted cap, unlike PressureVent)
// with an outward flow arrow, for large-capacity emergency relief to atmosphere.
export default function EmergencyVent(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="22" y1="60" x2="22" y2="20" />
      <line x1="42" y1="60" x2="42" y2="20" />
      <line x1="22" y1="20" x2="42" y2="20" />
      <path d="M 32,20 L 32,6 M 27,10 L 32,6 L 37,10" />
    </SymbolSvg>
  )
}

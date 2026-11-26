import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Emergency stop (E-STOP) — mushroom-head pushbutton on an octagonal
// station plate, the standard stop-button convention.
export default function EmergencyStop(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 22,12 L 42,12 L 50,20 L 50,40 L 42,48 L 22,48 L 14,40 L 14,20 Z" />
      <circle cx="32" cy="30" r="12" />
    </SymbolSvg>
  )
}

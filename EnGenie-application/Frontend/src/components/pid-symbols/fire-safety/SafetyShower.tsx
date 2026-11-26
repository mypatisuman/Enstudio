import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Combination safety shower — EmergencyShower's overhead head PLUS
// EyeWashStation's bowl on the same pedestal (the combined unit found at
// most process-area stations).
export default function SafetyShower(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="32" y1="2" x2="32" y2="10" />
      <path d="M 20,10 L 44,10 L 38,16 L 26,16 Z" />
      <path d="M 24,22 L 22,27 M 30,22 L 29,27 M 36,22 L 37,27 M 42,22 L 44,27" />
      <line x1="32" y1="16" x2="32" y2="40" />
      <path d="M 18,40 A 14 6 0 0 0 46,40 Z" />
      <circle cx="26" cy="36" r="1.6" />
      <circle cx="38" cy="36" r="1.6" />
      <line x1="32" y1="40" x2="32" y2="54" />
      <line x1="22" y1="60" x2="42" y2="60" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Emergency (drench) shower — overhead shower head with a pull-handle
// activator on a pedestal — shower only, no eyewash bowl (see SafetyShower).
export default function EmergencyShower(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="32" y1="4" x2="32" y2="14" />
      <path d="M 20,14 L 44,14 L 38,20 L 26,20 Z" />
      <path d="M 24,26 L 22,32 M 30,26 L 29,32 M 36,26 L 37,32 M 42,26 L 44,32" />
      <line x1="20" y1="18" x2="14" y2="18" />
      <line x1="14" y1="18" x2="14" y2="30" />
      <line x1="32" y1="20" x2="32" y2="52" />
      <line x1="22" y1="58" x2="42" y2="58" />
    </SymbolSvg>
  )
}

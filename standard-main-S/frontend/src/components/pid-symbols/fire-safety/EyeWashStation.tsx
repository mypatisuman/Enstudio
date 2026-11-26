import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Eye wash station — twin low-mounted wash nozzle bowl on a pedestal, no
// overhead shower head (see EmergencyShower / SafetyShower).
export default function EyeWashStation(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 18,36 A 14 6 0 0 0 46,36 Z" />
      <circle cx="26" cy="32" r="2" />
      <circle cx="38" cy="32" r="2" />
      <line x1="32" y1="36" x2="32" y2="52" />
      <line x1="22" y1="58" x2="42" y2="58" />
    </SymbolSvg>
  )
}

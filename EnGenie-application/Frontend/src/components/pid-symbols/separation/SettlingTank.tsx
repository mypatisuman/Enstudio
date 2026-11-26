import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Settling tank — open-top tank (no roof line, per the open/atmospheric
// convention already used by AtmosphericTank's 'floating' variant) with a
// sloped/conical bottom, an overflow nozzle near the rim, and a sludge
// outlet at the point.
export default function SettlingTank(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 14,10 L 14,36 L 32,54 L 50,36 L 50,10" />
      <line x1="50" y1="18" x2="57" y2="18" />
      <line x1="32" y1="54" x2="32" y2="60" />
    </SymbolSvg>
  )
}

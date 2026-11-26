import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Cyclone — cylindrical upper section over a conical lower section,
// tangential inlet, top gas outlet, pointed bottom solids discharge.
export default function Cyclone(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 18,12 L 46,12 L 46,32 L 34,54 L 30,54 L 18,32 Z" />
      <line x1="32" y1="12" x2="32" y2="4" />
      <line x1="6" y1="18" x2="18" y2="18" />
      <line x1="32" y1="54" x2="32" y2="60" />
    </SymbolSvg>
  )
}

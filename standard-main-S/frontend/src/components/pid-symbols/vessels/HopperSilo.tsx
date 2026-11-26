import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Hopper / silo — cylindrical body, open top, conical discharge to a bottom
// outlet nozzle. Deliberately not a rounded rectangle.
export default function HopperSilo(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="18" y1="8" x2="46" y2="8" />
      <path d="M 18,8 L 18,34 L 32,50 L 46,34 L 46,8" />
      <line x1="32" y1="50" x2="32" y2="59" />
    </SymbolSvg>
  )
}

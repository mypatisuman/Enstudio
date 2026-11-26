import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Cable junction — multiple cable runs meeting at a splice point (filled
// dot at the junction), distinct from JunctionBox's enclosure symbol.
export default function CableJunction(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="32" y2="32" />
      <line x1="32" y1="32" x2="60" y2="18" />
      <line x1="32" y1="32" x2="60" y2="46" />
      <circle cx="32" cy="32" r="3" />
    </SymbolSvg>
  )
}

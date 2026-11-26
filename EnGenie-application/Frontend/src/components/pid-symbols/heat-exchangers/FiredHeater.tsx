import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Fired heater — furnace box, stack with smoke chevrons, vertical radiant
// tubes, and a burner flame — unmistakably not a generic rectangle.
export default function FiredHeater(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="28" y="4" width="8" height="14" />
      <path d="M 29,3 L 32,0 L 35,3" />
      <rect x="14" y="18" width="36" height="36" />
      <line x1="22" y1="22" x2="22" y2="46" />
      <line x1="42" y1="22" x2="42" y2="46" />
      <path d="M 28,50 Q 32,42 32,50 Q 36,42 36,50" />
      <line x1="8" y1="30" x2="14" y2="30" />
      <line x1="50" y1="30" x2="56" y2="30" />
    </SymbolSvg>
  )
}

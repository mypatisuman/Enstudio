import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Furnace reactor (cracking/pyrolysis furnace) — enclosure with a full
// serpentine radiant coil (not the two straight tubes the heat-exchangers
// library's FiredHeater uses — a reaction furnace's coil dominates the
// box), a burner flame at the base, and a stack.
export default function FurnaceReactor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="28" y="4" width="8" height="14" />
      <path d="M 29,3 L 32,0 L 35,3" />
      <rect x="14" y="18" width="36" height="36" />
      <path d="M 20,24 L 44,24 L 44,30 L 20,30 L 20,36 L 44,36 L 44,42 L 20,42 L 20,48 L 44,48" />
      <path d="M 28,50 Q 32,44 32,50 Q 36,44 36,50" />
      <line x1="8" y1="30" x2="14" y2="30" />
      <line x1="50" y1="30" x2="56" y2="30" />
    </SymbolSvg>
  )
}

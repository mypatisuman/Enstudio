import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Superheater — coil bundle (same coil convention as Economizer) sitting
// over a furnace heating section (hatched band at the base) with a steam
// outlet — the furnace band is what marks it apart from Economizer/Evaporator.
export default function Superheater(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={16} y={12} w={32} h={30} capRy={8} />
      <path d="M 22,18 Q 28,22 22,26 Q 28,30 22,34" />
      <path d="M 32,18 Q 38,22 32,26 Q 38,30 32,34" />
      <path d="M 42,18 Q 48,22 42,26 Q 48,30 42,34" />
      <line x1="16" y1="42" x2="48" y2="42" />
      <path d="M 20,42 L 24,50 M 28,42 L 32,50 M 36,42 L 40,50 M 44,42 L 48,50" />
      <line x1="16" y1="50" x2="48" y2="50" />
      <line x1="32" y1="4" x2="32" y2="12" />
    </SymbolSvg>
  )
}

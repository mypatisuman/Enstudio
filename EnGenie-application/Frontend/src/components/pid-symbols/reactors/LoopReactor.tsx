import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Loop reactor — a narrow vessel with an external circulation loop (piping
// out the bottom, through an inline circulation pump, back in near the
// top) — the loop itself is the reactor's defining feature, not internals.
export default function LoopReactor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={16} y={10} w={16} h={36} capRy={6} />
      <line x1="32" y1="14" x2="48" y2="14" />
      <line x1="48" y1="14" x2="48" y2="46" />
      <line x1="48" y1="46" x2="32" y2="46" />
      <circle cx="48" cy="30" r="6" />
      <line x1="42" y1="30" x2="54" y2="30" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Hairpin exchanger — tight U-shaped double pipe (parallel tube run folded
// back on itself), distinct from DoublePipeHX's single straight pass.
export default function HairpinHX(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 10,14 L 40,14 A 12 12 0 0 1 40,38 L 14,38 A 8 8 0 0 0 14,54 L 40,54" />
      <path d="M 10,22 L 34,22 A 4 4 0 0 1 34,30 L 22,30 A 4 4 0 0 0 22,46 L 40,46" />
      <line x1="2" y1="14" x2="10" y2="14" />
      <line x1="2" y1="22" x2="10" y2="22" />
      <line x1="40" y1="54" x2="46" y2="54" />
      <line x1="40" y1="46" x2="46" y2="46" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Coalescer — vertical vessel with a dense cross-hatched coalescing
// cartridge (a taller, denser block than Demister's thin mesh band),
// inlet low, outlet high.
export default function Coalescer(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={20} y={10} w={24} h={44} capRy={8} />
      <line x1="20" y1="20" x2="44" y2="20" />
      <line x1="20" y1="38" x2="44" y2="38" />
      <path d="M 20,20 L 44,38 M 44,20 L 20,38 M 20,26 L 44,26 M 20,32 L 44,32" />
      <line x1="32" y1="2" x2="32" y2="10" />
      <line x1="20" y1="46" x2="13" y2="46" />
    </SymbolSvg>
  )
}

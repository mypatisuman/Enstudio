import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Demister — vertical vessel with a wire-mesh pad band (fine cross-hatch,
// denser than a fixed-bed's coarse X) near the top, inlet low, outlet high.
export default function Demister(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={20} y={10} w={24} h={44} capRy={8} />
      <line x1="20" y1="22" x2="44" y2="22" />
      <line x1="20" y1="32" x2="44" y2="32" />
      <path d="M 22,22 L 42,32 M 42,22 L 22,32 M 22,27 L 42,27" />
      <line x1="32" y1="2" x2="32" y2="10" />
      <line x1="20" y1="46" x2="13" y2="46" />
    </SymbolSvg>
  )
}

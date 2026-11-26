import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Catalytic cracker (FCCU) — tall narrow riser next to a shorter, wider
// regenerator vessel, each topped by a cyclone (inverted-cone) internal,
// with catalyst standpipes crossing between the two — the two-vessel
// riser/regenerator pair is the defining silhouette, unlike every other
// single-shell reactor in this library.
export default function CatalyticCracker(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={10} y={8} w={10} h={44} capRy={4} />
      <path d="M 12,14 L 18,14 L 15,20 Z" />
      <VerticalBody x={30} y={20} w={20} h={32} capRy={6} />
      <path d="M 34,26 L 46,26 L 40,34 Z" />
      <line x1="20" y1="44" x2="30" y2="30" />
      <line x1="30" y1="46" x2="20" y2="24" />
      <line x1="15" y1="52" x2="15" y2="60" />
      <line x1="40" y1="52" x2="40" y2="60" />
    </SymbolSvg>
  )
}

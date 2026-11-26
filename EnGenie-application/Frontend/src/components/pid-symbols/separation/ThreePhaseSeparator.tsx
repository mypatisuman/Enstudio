import { SymbolSvg } from './base'
import { HorizontalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Three-phase separator — horizontal vessel with an internal weir baffle
// splitting oil/water sections, plus a separate gas outlet on top —
// distinct from OilWaterSeparator by having three ports, not two.
export default function ThreePhaseSeparator(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <HorizontalBody x={8} y={20} w={44} h={20} />
      <line x1="34" y1="22" x2="34" y2="34" />
      <line x1="20" y1="14" x2="20" y2="20" />
      <line x1="44" y1="20" x2="44" y2="14" />
      <line x1="52" y1="26" x2="58" y2="26" />
      <line x1="8" y1="34" x2="2" y2="34" />
    </SymbolSvg>
  )
}

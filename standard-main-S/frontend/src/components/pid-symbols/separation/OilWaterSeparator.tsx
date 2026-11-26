import { SymbolSvg } from './base'
import { HorizontalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Oil-water separator — horizontal vessel with a partial-height weir
// baffle and two liquid outlets at different elevations (oil skims high,
// water draws low) — no gas outlet, unlike ThreePhaseSeparator.
export default function OilWaterSeparator(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <HorizontalBody x={8} y={20} w={44} h={20} />
      <line x1="34" y1="24" x2="34" y2="40" />
      <line x1="8" y1="26" x2="2" y2="26" />
      <line x1="52" y1="34" x2="58" y2="34" />
    </SymbolSvg>
  )
}

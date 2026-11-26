import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Plate & frame exchanger — compression-bolt frame with a straight vertical
// plate stack, distinct from the existing PlateHeatExchanger's diagonal
// corrugation hatch: this one shows the physical frame (bolts at all four
// corners) rather than the corrugation pattern.
export default function PlateFrameHX(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="14" y="10" width="36" height="44" />
      {[20, 26, 32, 38, 44].map(x => <line key={x} x1={x} y1="12" x2={x} y2="52" />)}
      <circle cx="16" cy="12" r="1.6" />
      <circle cx="48" cy="12" r="1.6" />
      <circle cx="16" cy="52" r="1.6" />
      <circle cx="48" cy="52" r="1.6" />
      <line x1="8" y1="18" x2="14" y2="18" />
      <line x1="50" y1="18" x2="56" y2="18" />
      <line x1="8" y1="46" x2="14" y2="46" />
      <line x1="50" y1="46" x2="56" y2="46" />
    </SymbolSvg>
  )
}

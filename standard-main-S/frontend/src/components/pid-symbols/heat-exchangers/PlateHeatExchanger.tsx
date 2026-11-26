import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Plate HX — rectangular frame, corrugated-plate diagonal hatch, four
// corner-ish nozzles. Deliberately square/compact — distinct from the
// long horizontal shell-and-tube silhouette.
export default function PlateHeatExchanger(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="14" y="12" width="36" height="40" />
      {[18, 24, 30, 36, 42].map(x => <line key={x} x1={x} y1="14" x2={x + 6} y2="50" />)}
      <line x1="8" y1="20" x2="14" y2="20" />
      <line x1="8" y1="44" x2="14" y2="44" />
      <line x1="50" y1="20" x2="56" y2="20" />
      <line x1="50" y1="44" x2="56" y2="44" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Blast relief panel — larger hinged wall panel (vs. ExplosionVent's small
// dashed rupture insert) that swings open under overpressure; the hinge
// line and open-panel silhouette are the distinguishing features.
export default function BlastReliefPanel(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="8" y1="10" x2="8" y2="54" />
      <line x1="8" y1="10" x2="56" y2="10" />
      <line x1="8" y1="54" x2="56" y2="54" />
      <path d="M 8,18 L 40,8 M 8,46 L 40,56" />
      <path d="M 44,32 L 52,32 M 48,28 L 52,32 L 48,36" />
    </SymbolSvg>
  )
}

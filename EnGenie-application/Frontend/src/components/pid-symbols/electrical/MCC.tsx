import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Motor control center — cabinet with multiple starter/breaker cells
// stacked in a column (the row-of-cells silhouette is what distinguishes an
// MCC from a single Switchboard/DistributionPanel).
export default function MCC(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="14" y="8" width="36" height="48" />
      <line x1="14" y1="18" x2="50" y2="18" />
      <line x1="14" y1="28" x2="50" y2="28" />
      <line x1="14" y1="38" x2="50" y2="38" />
      <line x1="14" y1="48" x2="50" y2="48" />
      <rect x="18" y="20" width="6" height="6" />
      <rect x="18" y="30" width="6" height="6" />
      <rect x="18" y="40" width="6" height="6" />
      <rect x="18" y="50" width="6" height="4" />
    </SymbolSvg>
  )
}

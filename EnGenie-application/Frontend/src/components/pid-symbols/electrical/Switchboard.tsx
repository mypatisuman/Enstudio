import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Switchboard — vertical bus bar feeding multiple breaker/switch outgoing
// ways (the bus-with-branches silhouette distinguishes it from MCC's
// stacked starter cells and DistributionPanel's grid).
export default function Switchboard(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="18" y1="6" x2="18" y2="58" />
      <line x1="18" y1="16" x2="34" y2="16" />
      <line x1="18" y1="28" x2="34" y2="28" />
      <line x1="18" y1="40" x2="34" y2="40" />
      <line x1="18" y1="52" x2="34" y2="52" />
      <rect x="34" y="12" width="8" height="8" />
      <rect x="34" y="24" width="8" height="8" />
      <rect x="34" y="36" width="8" height="8" />
      <rect x="34" y="48" width="8" height="8" />
      <line x1="42" y1="16" x2="50" y2="16" />
      <line x1="42" y1="28" x2="50" y2="28" />
      <line x1="42" y1="40" x2="50" y2="40" />
      <line x1="42" y1="52" x2="50" y2="52" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Distribution panel — cabinet with a grid of circuit slots (breaker
// panel/loadcenter), distinct from Switchboard's single bus-with-branches.
export default function DistributionPanel(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="12" y="10" width="40" height="44" />
      {[18, 26, 34, 42].map(y => <line key={y} x1="12" y1={y} x2="52" y2={y} />)}
      <line x1="32" y1="10" x2="32" y2="54" />
      <line x1="32" y1="2" x2="32" y2="10" />
    </SymbolSvg>
  )
}

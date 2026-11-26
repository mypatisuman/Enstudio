import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Utility header — trunk manifold with branch takeoffs (same drafting
// convention as SteamHeader); covers Main/Branch/Distribution Header since
// per ISO 10628 those are the same manifold symbol at different tag levels,
// not different shapes.
export default function UtilityHeader(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="60" y2="32" strokeWidth={3} />
      <line x1="16" y1="32" x2="16" y2="18" />
      <line x1="32" y1="32" x2="32" y2="18" />
      <line x1="48" y1="32" x2="48" y2="18" />
      <line x1="24" y1="32" x2="24" y2="46" />
      <line x1="40" y1="32" x2="40" y2="46" />
    </SymbolSvg>
  )
}

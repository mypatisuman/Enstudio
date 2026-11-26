import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Steam header — trunk manifold line with multiple perpendicular branch
// takeoffs, the standard header/manifold drafting convention.
export default function SteamHeader(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="60" y2="32" />
      <line x1="16" y1="32" x2="16" y2="18" />
      <line x1="32" y1="32" x2="32" y2="18" />
      <line x1="48" y1="32" x2="48" y2="18" />
      <line x1="24" y1="32" x2="24" y2="46" />
      <line x1="40" y1="32" x2="40" y2="46" />
    </SymbolSvg>
  )
}

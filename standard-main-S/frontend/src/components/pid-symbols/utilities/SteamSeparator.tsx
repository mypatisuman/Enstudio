import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Steam separator — vertical vessel with internal chevron baffles that
// knock moisture out of wet steam, dry-steam outlet top, condensate bottom.
export default function SteamSeparator(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={18} y={12} w={28} h={36} capRy={8} />
      <path d="M 22,26 L 32,20 L 42,26 M 22,34 L 32,28 L 42,34" />
      <line x1="18" y1="22" x2="11" y2="22" />
      <line x1="32" y1="4" x2="32" y2="12" />
      <line x1="32" y1="56" x2="32" y2="62" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Gas turbine — tapered casing with an added combustor bump on top
// (distinguishing it from SteamTurbine, which has none) plus intake and
// exhaust flow arrows at both ends.
export default function GasTurbine(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 8,16 L 8,44 L 52,36 L 52,24 Z" />
      <rect x="20" y="6" width="14" height="10" />
      <line x1="27" y1="16" x2="27" y2="20" />
      <line x1="16" y1="18" x2="16" y2="42" />
      <line x1="32" y1="21" x2="32" y2="39" />
      <line x1="40" y1="23" x2="40" y2="37" />
      <path d="M 2,30 L 8,30 M 4,26 L 8,30 L 4,34" />
      <path d="M 52,30 L 60,30 M 56,26 L 60,30 L 56,34" />
    </SymbolSvg>
  )
}

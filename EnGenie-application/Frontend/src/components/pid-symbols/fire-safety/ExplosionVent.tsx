import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Explosion vent — rupture panel set into a wall/duct with burst-direction
// arrows, the ATEX/NFPA-68 explosion-relief panel convention.
export default function ExplosionVent(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="16" x2="4" y2="48" />
      <line x1="60" y1="16" x2="60" y2="48" />
      <rect x="16" y="16" width="32" height="32" strokeDasharray="4 3" />
      <path d="M 32,16 L 32,4 M 27,8 L 32,4 L 37,8" />
      <path d="M 16,32 L 4,32 M 8,27 L 4,32 L 8,37" />
      <path d="M 48,32 L 60,32 M 56,27 L 60,32 L 56,37" />
    </SymbolSvg>
  )
}

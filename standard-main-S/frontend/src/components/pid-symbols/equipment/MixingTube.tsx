import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Mixing tube (inline static mixer) — pipe housing with repeated static
// mixing elements (X-pattern baffles), flanged process connections both ends.
export default function MixingTube(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="2" y1="32" x2="10" y2="32" />
      <line x1="10" y1="20" x2="10" y2="44" />
      <rect x="10" y="20" width="44" height="24" />
      <path d="M 14,22 L 22,42 M 22,22 L 14,42 M 24,22 L 32,42 M 32,22 L 24,42 M 34,22 L 42,42 M 42,22 L 34,42 M 44,22 L 50,38 M 50,22 L 44,38" />
      <line x1="54" y1="20" x2="54" y2="44" />
      <line x1="54" y1="32" x2="62" y2="32" />
    </SymbolSvg>
  )
}

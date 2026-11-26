import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Centrifuge — rotating basket/drum (domed housing) with a drive motor,
// feed inlet, and separate liquid/solids outlets — distinct from the
// cyclone's straight-sided cone.
export default function Centrifuge(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 14,44 L 14,28 Q 14,14 32,14 Q 50,14 50,28 L 50,44" />
      <line x1="14" y1="44" x2="50" y2="44" />
      <rect x="44" y="6" width="10" height="8" />
      <line x1="49" y1="14" x2="49" y2="18" />
      <line x1="4" y1="24" x2="14" y2="24" />
      <line x1="24" y1="44" x2="24" y2="52" />
      <line x1="40" y1="44" x2="40" y2="52" />
    </SymbolSvg>
  )
}

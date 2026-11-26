import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Lighting fixture — luminaire circle with radiating rays (standard light
// symbol) and a supply lead.
export default function LightingFixture(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="34" r="14" />
      <line x1="32" y1="16" x2="32" y2="22" />
      <line x1="32" y1="46" x2="32" y2="52" />
      <line x1="14" y1="34" x2="20" y2="34" />
      <line x1="44" y1="34" x2="50" y2="34" />
      <line x1="20" y1="22" x2="24" y2="26" />
      <line x1="44" y1="22" x2="40" y2="26" />
      <line x1="20" y1="46" x2="24" y2="42" />
      <line x1="44" y1="46" x2="40" y2="42" />
      <line x1="32" y1="8" x2="32" y2="14" />
    </SymbolSvg>
  )
}

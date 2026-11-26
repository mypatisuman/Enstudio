import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Sprinkler head — pipe drop to a deflector plate (concentric-arc spray
// pattern below it), the standard automatic-sprinkler symbol.
export default function SprinklerHead(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="32" y1="6" x2="32" y2="30" />
      <circle cx="32" cy="34" r="4" />
      <line x1="20" y1="40" x2="44" y2="40" />
      <path d="M 20,46 Q 32,52 44,46" />
      <path d="M 24,52 Q 32,56 40,52" />
    </SymbolSvg>
  )
}

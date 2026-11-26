import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Escape breathing apparatus — wall-mounted cabinet with a respirator mask
// silhouette (EEBA/self-rescue unit), distinct from FireExtinguisher's
// cylinder-and-hose shape.
export default function EscapeBreathingApparatus(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="14" y="10" width="36" height="44" />
      <path d="M 24,24 Q 24,16 32,16 Q 40,16 40,24 L 40,34 Q 40,42 32,42 Q 24,42 24,34 Z" />
      <circle cx="27" cy="28" r="3" />
      <circle cx="37" cy="28" r="3" />
      <path d="M 28,36 Q 32,39 36,36" />
    </SymbolSvg>
  )
}

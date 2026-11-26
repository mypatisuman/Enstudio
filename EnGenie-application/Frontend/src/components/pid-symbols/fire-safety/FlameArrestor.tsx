import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Flame arrestor — in-line pipe device with an internal mesh/screen
// element that quenches flame propagation, distinct from a plain Filter
// (which is a process-separation device, not a fire-protection device).
export default function FlameArrestor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="20" y2="32" />
      <rect x="20" y="18" width="24" height="28" />
      <path d="M 24,22 L 40,42 M 28,22 L 40,38 M 32,22 L 40,34 M 24,26 L 36,42 M 24,30 L 32,42 M 24,34 L 28,42" />
      <line x1="44" y1="32" x2="60" y2="32" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Lightning protection (air terminal / surge arrestor to earth) —
// lightning bolt down to the Ground symbol's descending bars.
export default function LightningProtection(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 34,4 L 24,26 L 32,26 L 28,44" />
      <line x1="32" y1="26" x2="32" y2="34" />
      <line x1="20" y1="34" x2="44" y2="34" />
      <line x1="24" y1="42" x2="40" y2="42" />
      <line x1="28" y1="50" x2="36" y2="50" />
    </SymbolSvg>
  )
}

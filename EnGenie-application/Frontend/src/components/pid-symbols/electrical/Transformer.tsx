import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Transformer — the standard two-overlapping-circles (coupled winding)
// symbol with primary/secondary leads top and bottom.
export default function Transformer(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="24" r="13" />
      <circle cx="32" cy="40" r="13" />
      <line x1="32" y1="4" x2="32" y2="11" />
      <line x1="32" y1="53" x2="32" y2="60" />
    </SymbolSvg>
  )
}

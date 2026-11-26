import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Junction box — plain box with the diagonal-cross "JB" convention,
// distinct from TerminalBox's row of numbered terminals.
export default function JunctionBox(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="16" y="16" width="32" height="32" />
      <line x1="16" y1="16" x2="48" y2="48" />
      <line x1="48" y1="16" x2="16" y2="48" />
      <line x1="32" y1="6" x2="32" y2="16" />
    </SymbolSvg>
  )
}

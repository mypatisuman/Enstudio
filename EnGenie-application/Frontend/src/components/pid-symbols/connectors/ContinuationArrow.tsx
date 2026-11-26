import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Continuation arrow — plain flow-continuation indicator (line breaks
// picking back up elsewhere on the same drawing).
export default function ContinuationArrow(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="50" y2="32" />
      <path d="M 40,22 L 58,32 L 40,42 Z" />
    </SymbolSvg>
  )
}

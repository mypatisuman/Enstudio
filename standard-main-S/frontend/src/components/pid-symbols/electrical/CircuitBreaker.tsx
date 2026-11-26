import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Circuit breaker — IEC 60617 breaker box (square on the line) with leads.
export default function CircuitBreaker(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="32" y1="4" x2="32" y2="22" />
      <rect x="22" y="22" width="20" height="20" />
      <line x1="32" y1="42" x2="32" y2="60" />
    </SymbolSvg>
  )
}

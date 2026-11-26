import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Clarifier — cylindrical settling basin with a conical sludge base,
// center feed pipe, and a rotating rake arm (rotation arrow) — distinct
// from the reactors' vertical shells since it's an open/atmospheric basin.
export default function Clarifier(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 12,14 L 12,38 L 32,52 L 52,38 L 52,14" />
      <line x1="10" y1="14" x2="54" y2="14" />
      <line x1="32" y1="6" x2="32" y2="14" />
      <line x1="14" y1="26" x2="50" y2="26" />
      <path d="M 46,22 A 6 6 0 0 1 46,30" />
      <line x1="32" y1="52" x2="32" y2="58" />
    </SymbolSvg>
  )
}

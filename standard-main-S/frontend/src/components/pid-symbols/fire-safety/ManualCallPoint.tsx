import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Manual call point — break-glass alarm box with the diagonal fracture
// line and activation button.
export default function ManualCallPoint(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="16" y="16" width="32" height="32" />
      <line x1="18" y1="18" x2="46" y2="46" />
      <circle cx="32" cy="32" r="5" />
    </SymbolSvg>
  )
}

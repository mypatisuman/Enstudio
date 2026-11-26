import { SymbolSvg } from './base'
import { BaseSupport } from './primitives'
import type { PidSymbolProps } from './types'

// Gearbox — housing with an internal gear train (multiple meshed gears,
// more than GearPump's simple pair) plus separate input and output shafts.
export default function Gearbox(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="12" y="14" width="40" height="32" />
      <circle cx="24" cy="24" r="7" />
      <circle cx="38" cy="24" r="7" />
      <circle cx="31" cy="37" r="7" />
      <line x1="4" y1="24" x2="12" y2="24" />
      <line x1="52" y1="24" x2="60" y2="24" />
      <BaseSupport />
    </SymbolSvg>
  )
}

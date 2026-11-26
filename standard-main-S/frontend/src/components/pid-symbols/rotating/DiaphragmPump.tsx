import { SymbolSvg } from './base'
import { Casing, BaseSupport } from './primitives'
import type { PidSymbolProps } from './types'

// Diaphragm pump — casing with a flexed diaphragm membrane and check
// valves at suction/discharge instead of a rotating impeller/gear/screw.
export default function DiaphragmPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <Casing />
      <path d="M 32,14 Q 40,22 32,30 Q 24,38 32,46" />
      <path d="M 8,30 L 14,30 L 11,26 Z M 8,30 L 14,30 L 11,34 Z" />
      <path d="M 50,30 L 56,30 L 53,26 Z M 50,30 L 56,30 L 53,34 Z" />
      <BaseSupport />
    </SymbolSvg>
  )
}

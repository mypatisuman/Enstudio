import { SymbolSvg } from './base'
import { BaseSupport } from './primitives'
import type { PidSymbolProps } from './types'

// Electric motor — housing with cooling-fin ridges and a drive shaft stub,
// no casing/impeller at all (it's the driver, not the driven machine).
export default function ElectricMotor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="10" y="16" width="38" height="28" />
      {[20, 25, 30, 35, 40].map(x => <line key={x} x1={x} y1="16" x2={x} y2="44" />)}
      <line x1="48" y1="30" x2="58" y2="30" />
      <BaseSupport />
    </SymbolSvg>
  )
}

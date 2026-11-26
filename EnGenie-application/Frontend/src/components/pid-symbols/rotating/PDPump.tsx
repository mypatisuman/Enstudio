import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Positive-displacement pump — casing with two intermeshing lobes (rotary
// lobe / gear set), distinct from the centrifugal pump's single volute vane.
export default function PDPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <Casing />
      <path d="M 20,18 Q 32,30 20,42" />
      <path d="M 44,18 Q 32,30 44,42" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

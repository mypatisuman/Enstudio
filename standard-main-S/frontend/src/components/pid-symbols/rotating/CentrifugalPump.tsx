import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Centrifugal pump — circular casing, curved volute/impeller vane, flow
// arrow toward discharge, skid base.
export default function CentrifugalPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <Casing />
      <path d="M 24,20 Q 40,22 40,30 Q 40,38 24,40" />
      <path d="M 22,30 L 38,30 M 33,25 L 38,30 L 33,35" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

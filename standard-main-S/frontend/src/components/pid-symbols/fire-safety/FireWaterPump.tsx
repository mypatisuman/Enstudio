import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from '../rotating/primitives'
import type { PidSymbolProps } from './types'

// Fire water pump — centrifugal-pump casing (same convention as the
// rotating library) with a small flame mark identifying fire-water service.
export default function FireWaterPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <Casing />
      <path d="M 30,26 Q 34,20 30,15 Q 26,20 30,26 Q 34,24 30,26" />
      <path d="M 22,30 L 38,30 M 33,25 L 38,30 L 33,35" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

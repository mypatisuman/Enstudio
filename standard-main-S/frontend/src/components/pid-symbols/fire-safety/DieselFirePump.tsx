import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from '../rotating/primitives'
import type { PidSymbolProps } from './types'

// Diesel-driven fire pump — FireWaterPump casing with a diesel engine skid
// attached, the same driver convention as the rotating library's
// DieselGenerator.
export default function DieselFirePump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <Casing />
      <path d="M 22,30 L 38,30 M 33,25 L 38,30 L 33,35" />
      <SuctionNozzle />
      <DischargeNozzle />
      <rect x="10" y="12" width="16" height="10" />
      <line x1="18" y1="22" x2="18" y2="16" />
      <BaseSupport />
    </SymbolSvg>
  )
}

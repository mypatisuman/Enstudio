import { SymbolSvg } from './base'
import { BaseSupport, SuctionNozzle, DischargeNozzle } from '../rotating/primitives'
import type { PidSymbolProps } from './types'

// Jockey pump — small pressure-maintenance pump alongside the main fire
// pump; drawn noticeably smaller than FireWaterPump's casing.
export default function JockeyPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="30" r="10" />
      <path d="M 26,30 L 38,30 M 33,26 L 38,30 L 33,34" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

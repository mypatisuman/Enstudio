import { SymbolSvg } from './base'
import { BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Screw pump — elongated cylindrical housing with twin helical screw
// rotors (zigzag threads), distinct from GearPump's round intermeshing gears.
export default function ScrewPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="10" y="18" width="44" height="24" />
      <path d="M 14,22 L 22,30 L 14,38 M 22,22 L 30,30 L 22,38 M 30,22 L 38,30 L 30,38 M 38,22 L 46,30 L 38,38 M 46,22 L 50,26" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

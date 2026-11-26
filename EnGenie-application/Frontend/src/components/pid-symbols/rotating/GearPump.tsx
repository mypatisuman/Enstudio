import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Gear pump — casing with two intermeshing external gears (teeth ticks
// around each circle), the positive-displacement mechanism that separates
// it from the centrifugal pump's single volute vane.
export default function GearPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <Casing />
      <circle cx="25" cy="30" r="8" />
      <circle cx="39" cy="30" r="8" />
      <path d="M 25,22 L 25,18 M 25,42 L 25,38 M 17,30 L 13,30 M 33,30 L 37,30" />
      <path d="M 39,22 L 39,18 M 39,42 L 39,38 M 47,30 L 51,30 M 31,30 L 27,30" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

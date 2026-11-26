import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Peristaltic pump — casing with the flexible tube looped around the
// inside of the housing and rollers (small circles) pressing against it —
// no impeller/gear/diaphragm at all, which is the point.
export default function PeristalticPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <Casing />
      <circle cx="32" cy="30" r="11" />
      <circle cx="32" cy="17" r="2.2" />
      <circle cx="43" cy="30" r="2.2" />
      <circle cx="32" cy="43" r="2.2" />
      <circle cx="21" cy="30" r="2.2" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

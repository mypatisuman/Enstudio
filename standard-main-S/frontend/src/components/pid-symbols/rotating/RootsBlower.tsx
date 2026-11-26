import { SymbolSvg } from './base'
import { BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Roots blower — twin-lobe positive-displacement rotors (peanut-shaped
// figure-eight pair) in a housing, distinct from GearPump's round gears
// and CentrifugalBlower's volute.
export default function RootsBlower(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="12" y="14" width="40" height="32" />
      <circle cx="32" cy="23" r="7" />
      <circle cx="32" cy="37" r="7" />
      <circle cx="24" cy="30" r="7" />
      <circle cx="40" cy="30" r="7" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

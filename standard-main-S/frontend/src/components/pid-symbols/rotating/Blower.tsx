import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Blower / fan — casing with a multi-blade pinwheel (low-pressure gas
// mover), grouped with the compressors by color since it's still a
// gas-service rotating machine, but visually distinct via open blades
// instead of a solid impeller wheel.
export default function Blower(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props} stroke={props.stroke ?? '#6366F1'}>
      <Casing />
      <path d="M 32,24 Q 37,27 32,30 Q 27,27 32,24" />
      <path d="M 38,30 Q 35,35 32,30 Q 35,25 38,30" />
      <path d="M 32,36 Q 27,33 32,30 Q 37,33 32,36" />
      <path d="M 26,30 Q 29,25 32,30 Q 29,35 26,30" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

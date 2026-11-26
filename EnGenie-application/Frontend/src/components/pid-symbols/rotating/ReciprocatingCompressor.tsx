import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Reciprocating compressor — casing with an internal cylinder/piston/
// connecting-rod arrangement instead of a rotary impeller.
export default function ReciprocatingCompressor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props} stroke={props.stroke ?? '#6366F1'}>
      <Casing />
      <rect x="30" y="23" width="14" height="14" />
      <line x1="30" y1="30" x2="18" y2="30" />
      <circle cx="18" cy="30" r="2.5" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

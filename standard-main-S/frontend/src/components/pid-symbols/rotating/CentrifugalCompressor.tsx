import { SymbolSvg } from './base'
import { Casing, BaseSupport, SuctionNozzle, DischargeNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Centrifugal compressor — same casing/base as the pumps, but indigo
// (per spec, compressors get their own stroke color) and a solid triangular
// impeller wheel instead of a curved volute vane.
export default function CentrifugalCompressor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props} stroke={props.stroke ?? '#6366F1'}>
      <Casing />
      <polygon points="24,20 42,30 24,40" />
      <SuctionNozzle />
      <DischargeNozzle />
      <BaseSupport />
    </SymbolSvg>
  )
}

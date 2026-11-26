import { SymbolSvg } from './base'
import { ReactorShell, TopNozzle, BottomNozzle, SideNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Trickle bed reactor — packed catalyst bed (support-plate + X-hatch, same
// convention as the reactors library's FixedBed) plus a liquid distributor
// above it (down-pointing ticks) and a collector cone at the base — the
// distributor/collector pair is what marks this as trickle-flow rather than
// a plain fixed bed.
export default function TrickleBedReactor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ReactorShell />
      <path d="M 23,20 L 23,24 M 28,20 L 28,24 M 36,20 L 36,24 M 41,20 L 41,24" />
      <line x1="20" y1="26" x2="44" y2="26" />
      <line x1="20" y1="42" x2="44" y2="42" />
      <path d="M 22,26 L 42,42 M 42,26 L 22,42" />
      <path d="M 26,48 L 32,54 L 38,48" />
      <TopNozzle />
      <BottomNozzle />
      <SideNozzle y={22} side="left" />
    </SymbolSvg>
  )
}

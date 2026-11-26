import { SymbolSvg } from './base'
import { ReactorShell, TopNozzle, BottomNozzle, SideNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Fixed bed — vessel with a cross-hatched catalyst-bed section held between
// two support-plate lines.
export default function FixedBed(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ReactorShell />
      <line x1="20" y1="26" x2="44" y2="26" />
      <line x1="20" y1="42" x2="44" y2="42" />
      <path d="M 22,26 L 42,42 M 42,26 L 22,42" />
      <TopNozzle />
      <BottomNozzle />
      <SideNozzle y={24} side="left" />
      <SideNozzle y={44} side="right" />
    </SymbolSvg>
  )
}

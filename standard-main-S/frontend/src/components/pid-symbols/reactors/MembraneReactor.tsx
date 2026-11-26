import { SymbolSvg } from './base'
import { ReactorShell, TopNozzle, SideNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Membrane reactor — reactor shell with internal membrane-module layers
// (parallel diagonal lines, same convention as the separation library's
// Membrane) and three distinct ports: feed top, permeate/retentate sides.
export default function MembraneReactor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ReactorShell />
      <line x1="24" y1="44" x2="34" y2="20" />
      <line x1="30" y1="44" x2="40" y2="20" />
      <TopNozzle />
      <SideNozzle y={44} side="left" />
      <SideNozzle y={30} side="right" />
    </SymbolSvg>
  )
}

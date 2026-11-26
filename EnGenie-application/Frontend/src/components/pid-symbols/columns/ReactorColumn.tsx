import { SymbolSvg } from './base'
import { ColumnShell, TopNozzle, BottomNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Reactor column — tray-column-height shell with a fixed-bed catalyst
// section (support plates + X-hatch, same convention as the reactors
// library's FixedBed) instead of trays or packing.
export default function ReactorColumn(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ColumnShell />
      <line x1="22" y1="20" x2="42" y2="20" />
      <line x1="22" y1="44" x2="42" y2="44" />
      <path d="M 22,20 L 42,44 M 42,20 L 22,44" />
      <TopNozzle />
      <BottomNozzle />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { ReactorShell, TopNozzle, BottomNozzle, SideNozzle } from './primitives'
import type { PidSymbolProps } from './types'

const BUBBLES: [number, number][] = [
  [25, 22], [30, 26], [36, 21], [39, 29], [27, 32],
  [34, 34], [24, 28], [40, 24], [30, 38], [37, 40],
]

// Bubble column reactor — reactor shell, gas sparger at the base, and gas
// bubbles rising through the liquid (no mechanical agitator — mixing is by
// the rising gas itself, which is what separates this from a CSTR).
export default function BubbleColumnReactor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ReactorShell />
      {BUBBLES.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1" />)}
      <line x1="24" y1="44" x2="40" y2="44" strokeDasharray="2 2" />
      <TopNozzle />
      <BottomNozzle />
      <SideNozzle y={24} side="left" />
    </SymbolSvg>
  )
}

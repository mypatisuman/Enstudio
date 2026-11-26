import { SymbolSvg } from './base'
import { ReactorShell, TopNozzle, BottomNozzle, SideNozzle } from './primitives'
import type { PidSymbolProps } from './types'

const PARTICLES: [number, number][] = [
  [25, 26], [30, 30], [36, 25], [39, 33], [27, 36],
  [34, 38], [24, 32], [40, 28], [30, 22],
]

// Fluidized bed — scattered particle dots (not a static hatch) above a
// distributor plate, with an upward flow arrow through the bed.
export default function FluidizedBed(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ReactorShell />
      {PARTICLES.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="0.9" />)}
      <line x1="20" y1="42" x2="44" y2="42" strokeDasharray="2 2" />
      <path d="M 32,40 L 32,22 M 28,26 L 32,22 L 36,26" />
      <TopNozzle />
      <SideNozzle y={44} side="left" />
      <BottomNozzle />
    </SymbolSvg>
  )
}

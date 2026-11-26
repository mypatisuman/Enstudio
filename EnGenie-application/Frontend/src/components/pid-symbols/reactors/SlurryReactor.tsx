import { SymbolSvg } from './base'
import { ReactorShell, TopNozzle, BottomNozzle, SideNozzle } from './primitives'
import type { PidSymbolProps } from './types'

const PARTICLES: [number, number][] = [
  [26, 42], [31, 45], [36, 41], [29, 38], [34, 47], [24, 46],
]

// Slurry reactor — CSTR-style agitator shaft/impeller (mechanical mixing,
// unlike the bubble column) with catalyst particles suspended in the lower
// liquid region instead of a fixed bed.
export default function SlurryReactor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ReactorShell />
      <line x1="32" y1="6" x2="32" y2="34" />
      <path d="M 26,31 L 32,35 L 26,39 Z M 38,31 L 32,35 L 38,39 Z" />
      {PARTICLES.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1" />)}
      <TopNozzle />
      <BottomNozzle />
      <SideNozzle y={24} side="left" />
    </SymbolSvg>
  )
}

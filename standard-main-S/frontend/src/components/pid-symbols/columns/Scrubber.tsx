import { SymbolSvg } from './base'
import { ColumnShell, TopNozzle, BottomNozzle } from './primitives'
import type { PidSymbolProps } from './types'

// Scrubber — spray nozzles near the top, mist eliminator (dashed band) below
// them, bottom sump, top gas outlet, side gas inlet near the bottom.
export default function Scrubber(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ColumnShell />
      {/* Spray nozzles */}
      <path d="M 26,15 L 29,20 M 29,20 L 26,25 M 29,20 L 32,25" />
      <path d="M 32,15 L 32,25" />
      <path d="M 38,15 L 35,20 M 35,20 L 38,25 M 35,20 L 32,25" />
      {/* Mist eliminator */}
      <line x1="24" y1="30" x2="40" y2="30" strokeDasharray="2 2" />
      <line x1="24" y1="34" x2="40" y2="34" strokeDasharray="2 2" />
      <TopNozzle />
      <BottomNozzle />
    </SymbolSvg>
  )
}

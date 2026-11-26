import { SymbolSvg } from './base'
import { ReactorShell, BottomNozzle, SideNozzle, Impeller } from './primitives'
import type { PidSymbolProps } from './types'

// Batch reactor — CSTR's shaft, but with a charging-funnel top port and TWO
// impeller stages (the "larger mixing arrangement" that separates it from
// a CSTR's single impeller) plus a jacket line tracing the shell.
export default function BatchReactor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 25,0 L 39,0 L 34,6 L 30,6 Z" />
      <ReactorShell />
      <path d="M 18,22 L 18,50 M 46,22 L 46,50" strokeDasharray="1 2" opacity="0.6" />
      <line x1="32" y1="6" x2="32" y2="46" />
      <Impeller y={32} />
      <Impeller y={44} />
      <BottomNozzle />
      <SideNozzle y={24} side="left" />
      <SideNozzle y={24} side="right" />
    </SymbolSvg>
  )
}

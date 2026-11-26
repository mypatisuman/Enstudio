import { SymbolSvg } from './base'
import { ReactorShell, TopNozzle, BottomNozzle, SideNozzle, Impeller } from './primitives'
import type { PidSymbolProps } from './types'

// CSTR — vessel + top motor + agitator shaft + bowtie impeller + one side
// inlet/outlet + bottom drain.
export default function CSTR(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="27" y="0" width="10" height="6" />
      <ReactorShell />
      <line x1="32" y1="6" x2="32" y2="40" />
      <Impeller y={43} />
      <TopNozzle />
      <BottomNozzle />
      <SideNozzle y={24} side="left" />
      <SideNozzle y={24} side="right" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { ColumnShell, TopNozzle, BottomNozzle, PackingMesh } from './primitives'
import type { PidSymbolProps } from './types'

// Absorber — packed shell (same internals convention as PackedColumn),
// vapor outlet top, liquid outlet bottom.
export default function Absorber(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ColumnShell />
      <PackingMesh />
      <TopNozzle />
      <BottomNozzle />
    </SymbolSvg>
  )
}

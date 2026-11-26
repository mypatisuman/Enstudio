import { SymbolSvg } from './base'
import { ColumnShell, TopNozzle, BottomNozzle, PackingMesh } from './primitives'
import type { PidSymbolProps } from './types'

// Packed column — same shell as TrayColumn, diamond-mesh packing instead of
// tray lines, top/bottom nozzles.
export default function PackedColumn(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ColumnShell />
      <PackingMesh />
      <TopNozzle />
      <BottomNozzle />
    </SymbolSvg>
  )
}

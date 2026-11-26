import { SymbolSvg } from './base'
import { ColumnShell, TopNozzle, BottomNozzle, TrayLines } from './primitives'
import type { PidSymbolProps } from './types'

// Tray column — cylindrical shell, dished heads, internal tray lines,
// top vapor outlet, bottom liquid outlet.
export default function TrayColumn(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ColumnShell />
      <TrayLines />
      <TopNozzle />
      <BottomNozzle />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { ColumnShell, TopNozzle, BottomNozzle, TrayLines } from './primitives'
import type { PidSymbolProps } from './types'

// Stripper — same tray-column shell/internals as TrayColumn.
export default function Stripper(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ColumnShell />
      <TrayLines />
      <TopNozzle />
      <BottomNozzle />
    </SymbolSvg>
  )
}

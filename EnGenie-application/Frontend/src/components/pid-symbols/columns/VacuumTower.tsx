import { SymbolSvg } from './base'
import { ColumnShell, TopNozzle, BottomNozzle, TrayLines } from './primitives'
import type { PidSymbolProps } from './types'

// Vacuum tower — tray-column shell with an extra large-diameter overhead
// nozzle (vacuum system tie-in) distinguishing it from TrayColumn.
export default function VacuumTower(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <ColumnShell />
      <TrayLines />
      <TopNozzle />
      <BottomNozzle />
      <line x1="42" y1="10" x2="50" y2="4" />
    </SymbolSvg>
  )
}

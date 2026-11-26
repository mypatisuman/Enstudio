import { SymbolSvg } from './base'
import { BaseSupport } from './primitives'
import type { PidSymbolProps } from './types'

// Vacuum pump — motor-driven housing (fin lines, like a compact rotary
// pump/motor skid) with a single vacuum connection and flow arrow — no
// suction/discharge pair since it draws from one vacuum line.
export default function VacuumPump(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="8" y="18" width="48" height="24" />
      {[24, 30, 36, 42].map(x => <line key={x} x1={x} y1="18" x2={x} y2="42" />)}
      <path d="M 56,30 L 62,30 M 58,26 L 62,30 L 58,34" />
      <BaseSupport />
    </SymbolSvg>
  )
}

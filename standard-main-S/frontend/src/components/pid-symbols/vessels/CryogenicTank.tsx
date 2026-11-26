import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Cryogenic tank — double-wall vacuum-jacketed vessel: outer shell, inner
// vessel, and a hatched vacuum-insulation gap between them (the hatching is
// what distinguishes it from DoubleWallTank's plain containment gap).
export default function CryogenicTank(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="12" y="14" width="40" height="40" />
      <rect x="19" y="21" width="26" height="26" />
      <line x1="14" y1="20" x2="17" y2="23" />
      <line x1="14" y1="28" x2="17" y2="31" />
      <line x1="14" y1="36" x2="17" y2="39" />
      <line x1="14" y1="44" x2="17" y2="47" />
      <line x1="47" y1="20" x2="50" y2="23" />
      <line x1="47" y1="28" x2="50" y2="31" />
      <line x1="47" y1="36" x2="50" y2="39" />
      <line x1="47" y1="44" x2="50" y2="47" />
      <line x1="32" y1="54" x2="32" y2="60" />
      <line x1="52" y1="34" x2="58" y2="34" />
    </SymbolSvg>
  )
}

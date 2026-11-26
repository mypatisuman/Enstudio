import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Membrane separator — housing with parallel membrane-layer lines and three
// distinct ports: feed (left), retentate (right), permeate (bottom).
export default function Membrane(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="12" y="18" width="40" height="28" />
      <line x1="18" y1="46" x2="30" y2="18" />
      <line x1="26" y1="46" x2="38" y2="18" />
      <line x1="34" y1="46" x2="46" y2="18" />
      <line x1="4" y1="26" x2="12" y2="26" />
      <line x1="52" y1="26" x2="60" y2="26" />
      <line x1="32" y1="46" x2="32" y2="54" />
    </SymbolSvg>
  )
}

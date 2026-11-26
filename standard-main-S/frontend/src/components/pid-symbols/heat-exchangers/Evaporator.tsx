import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Evaporator — vertical shell, straight vertical tube bundle, vapor outlet
// top, liquid outlet bottom, feed nozzle side.
export default function Evaporator(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={16} y={12} w={32} h={38} capRy={8} />
      {[24, 29, 34, 39].map(x => <line key={x} x1={x} y1="16" x2={x} y2="46" />)}
      <line x1="32" y1="4" x2="32" y2="12" />
      <line x1="32" y1="58" x2="32" y2="63" />
      <line x1="16" y1="26" x2="9" y2="26" />
    </SymbolSvg>
  )
}

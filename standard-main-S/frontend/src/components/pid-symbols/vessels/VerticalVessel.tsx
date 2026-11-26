import { SymbolSvg } from './base'
import { VerticalBody } from './primitives'
import type { PidSymbolProps } from './types'

// Vertical pressure vessel — cylindrical body, dished top/bottom heads,
// top + bottom nozzles.
export default function VerticalVessel(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody />
      <line x1="32" y1="10" x2="32" y2="3" />
      <line x1="32" y1="54" x2="32" y2="61" />
    </SymbolSvg>
  )
}

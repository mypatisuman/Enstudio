import { SymbolSvg } from './base'
import { HorizontalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Decanter centrifuge — horizontal bowl with an internal helical screw
// conveyor, separate liquid (side) and solids (end) discharges, on legs.
export default function Decanter(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <HorizontalBody x={8} y={20} w={44} h={20} />
      <path d="M 14,22 L 20,30 L 14,38 M 20,22 L 26,30 L 20,38 M 26,22 L 32,30 L 26,38 M 32,22 L 38,30 L 32,38 M 38,22 L 44,30 L 38,38" />
      <line x1="2" y1="30" x2="8" y2="30" />
      <line x1="20" y1="40" x2="20" y2="46" />
      <line x1="52" y1="30" x2="58" y2="30" />
      <line x1="16" y1="46" x2="16" y2="52" />
      <line x1="24" y1="46" x2="24" y2="52" />
    </SymbolSvg>
  )
}

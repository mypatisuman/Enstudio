import { SymbolSvg } from './base'
import { VerticalBody } from './primitives'
import type { PidSymbolProps } from './types'

// Pressure accumulator — vertical dished-head vessel, single top gas nozzle,
// single bottom liquid nozzle, optional internal gas/liquid interface line.
export default function Accumulator({ showInterface = true, ...props }:
  PidSymbolProps & { showInterface?: boolean }) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody />
      <line x1="32" y1="10" x2="32" y2="3" />
      <line x1="32" y1="54" x2="32" y2="61" />
      {showInterface && <line x1="20" y1="34" x2="44" y2="34" strokeDasharray="3 2" />}
    </SymbolSvg>
  )
}

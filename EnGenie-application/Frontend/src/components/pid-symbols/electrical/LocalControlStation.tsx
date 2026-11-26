import { SymbolSvg } from './base'
import { PanelBox } from './primitives'
import type { PidSymbolProps } from './types'

// Local control station — small field panel with start/stop pushbuttons,
// distinct from ControlPanel's gauge+selector instrumentation cabinet.
export default function LocalControlStation(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <PanelBox />
      <circle cx="24" cy="30" r="6" />
      <circle cx="40" cy="30" r="6" />
      <line x1="32" y1="52" x2="32" y2="58" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { PanelBox } from './primitives'
import type { PidSymbolProps } from './types'

// Control panel — panel with an indicator gauge and a selector switch,
// representing an operator instrumentation/control cabinet.
export default function ControlPanel(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <PanelBox />
      <circle cx="24" cy="28" r="7" />
      <line x1="24" y1="28" x2="28" y2="23" />
      <rect x="36" y="34" width="10" height="10" />
      <line x1="41" y1="34" x2="41" y2="26" />
      <line x1="32" y1="52" x2="32" y2="58" />
    </SymbolSvg>
  )
}

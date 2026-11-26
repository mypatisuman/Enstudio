import { SymbolSvg } from './base'
import { PanelBox } from './primitives'
import type { PidSymbolProps } from './types'

// UPS — panel with a battery cell mark plus an AC sine wave, showing both
// the stored-energy and inverter-output sides of the unit.
export default function UPS(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <PanelBox />
      <line x1="20" y1="24" x2="20" y2="34" />
      <line x1="24" y1="20" x2="24" y2="38" />
      <line x1="28" y1="24" x2="28" y2="34" />
      <path d="M 34,29 Q 38,21 42,29 Q 46,37 50,29" />
      <line x1="32" y1="52" x2="32" y2="58" />
    </SymbolSvg>
  )
}

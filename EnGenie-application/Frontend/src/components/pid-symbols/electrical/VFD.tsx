import { SymbolSvg } from './base'
import { PanelBox } from './primitives'
import type { PidSymbolProps } from './types'

// Variable frequency drive — panel with the sine-to-square (AC-to-variable
// output) waveform that's the standard inverter/VFD pictogram.
export default function VFD(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <PanelBox />
      <path d="M 16,26 Q 20,20 24,26 Q 28,32 32,26" />
      <path d="M 32,26 L 32,20 L 38,20 L 38,32 L 44,32 L 44,26" />
      <line x1="32" y1="52" x2="32" y2="58" />
    </SymbolSvg>
  )
}

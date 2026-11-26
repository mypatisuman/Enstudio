import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Heat detector — same ceiling dome as SmokeDetector, with a thermometer
// mark instead of smoke particles.
export default function HeatDetector(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 16,24 A 16 16 0 0 1 48,24 Z" />
      <line x1="16" y1="24" x2="48" y2="24" />
      <line x1="32" y1="28" x2="32" y2="38" />
      <circle cx="32" cy="41" r="3" />
    </SymbolSvg>
  )
}

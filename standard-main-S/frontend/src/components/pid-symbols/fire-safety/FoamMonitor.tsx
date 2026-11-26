import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Foam monitor — same swivel-riser convention as WaterMonitor, plus a foam
// induction chamber ahead of the nozzle barrel.
export default function FoamMonitor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="16" y1="58" x2="48" y2="58" />
      <line x1="32" y1="58" x2="32" y2="36" />
      <circle cx="32" cy="32" r="5" />
      <rect x="36" y="24" width="10" height="8" />
      <path d="M 46,28 L 56,22 M 52,20 L 56,22 L 54,26" />
    </SymbolSvg>
  )
}

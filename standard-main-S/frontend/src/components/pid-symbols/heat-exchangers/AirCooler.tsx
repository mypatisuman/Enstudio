import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Air cooler — finned bundle box with a 4-blade axial fan as the defining
// feature, process flow straight through left→right.
export default function AirCooler(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="8" y="12" width="48" height="24" />
      <line x1="12" y1="18" x2="52" y2="18" />
      <line x1="12" y1="30" x2="52" y2="30" />
      <g>
        <path d="M 32,26 Q 36,20 32,15 Q 28,20 32,26" />
        <path d="M 32,26 Q 38,28 44,26 Q 38,22 32,26" />
        <path d="M 32,26 Q 28,32 32,37 Q 36,32 32,26" />
        <path d="M 32,26 Q 26,24 20,26 Q 26,30 32,26" />
      </g>
      <line x1="2" y1="24" x2="8" y2="24" />
      <line x1="56" y1="24" x2="62" y2="24" />
    </SymbolSvg>
  )
}

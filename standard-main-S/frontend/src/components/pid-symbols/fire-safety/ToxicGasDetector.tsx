import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Toxic gas detector — same housing as GasDetector, plus a hazard triangle
// (exclamation) marking it as a toxic/personnel-hazard sensor rather than
// a combustible-gas sensor.
export default function ToxicGasDetector(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="18" y="16" width="28" height="28" />
      <path d="M 32,22 L 42,38 L 22,38 Z" />
      <line x1="32" y1="27" x2="32" y2="33" />
      <circle cx="32" cy="35.5" r="0.8" />
    </SymbolSvg>
  )
}

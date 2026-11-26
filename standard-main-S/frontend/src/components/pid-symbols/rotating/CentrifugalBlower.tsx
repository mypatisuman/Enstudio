import { SymbolSvg } from './base'
import { BaseSupport } from './primitives'
import type { PidSymbolProps } from './types'

// Centrifugal blower — volute (snail-shell) casing wrapping the impeller,
// with a tangential outlet duct — distinct from the existing Blower/Fan's
// plain circular housing with straight suction/discharge nozzles.
export default function CentrifugalBlower(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 32,10 A 18 18 0 1 0 49,33 L 58,30 L 58,22 L 44,20 A 18 18 0 0 0 32,10 Z" />
      <circle cx="30" cy="28" r="10" />
      <path d="M 30,28 L 34,20 M 30,28 L 38,26 M 30,28 L 36,34 M 30,28 L 26,36 M 30,28 L 22,32 M 30,28 L 22,22" />
      <line x1="6" y1="28" x2="12" y2="28" />
      <line x1="58" y1="26" x2="64" y2="26" />
      <BaseSupport />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Gas detector — wall-mount housing with a gas-cloud mark, distinct from
// FlameDetector's line-of-sight cone housing.
export default function GasDetector(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="18" y="16" width="28" height="28" />
      <path d="M 26,32 Q 22,26 28,24 Q 30,18 36,22 Q 42,20 42,26 Q 46,28 42,32 Z" />
    </SymbolSvg>
  )
}

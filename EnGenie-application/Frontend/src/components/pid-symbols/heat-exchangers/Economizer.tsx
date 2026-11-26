import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Economizer — vertical shell with a coiled (not straight) heat-recovery
// bundle and a gas flow-direction arrow through it, distinguishing it from
// Evaporator's plain straight tube bundle.
export default function Economizer(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={16} y={12} w={32} h={38} capRy={8} />
      <path d="M 22,18 Q 28,22 22,26 Q 28,30 22,34 Q 28,38 22,42" />
      <path d="M 32,18 Q 38,22 32,26 Q 38,30 32,34 Q 38,38 32,42" />
      <path d="M 42,18 Q 48,22 42,26 Q 48,30 42,34 Q 48,38 42,42" />
      <path d="M 12,30 L 20,30 M 16,26 L 20,30 L 16,34" />
      <line x1="32" y1="4" x2="32" y2="12" />
      <line x1="32" y1="58" x2="32" y2="63" />
    </SymbolSvg>
  )
}

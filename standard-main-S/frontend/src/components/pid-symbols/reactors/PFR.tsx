import { SymbolSvg } from './base'
import { HorizontalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// PFR — long horizontal tube, no agitator, flow-direction arrow inside.
export default function PFR(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <HorizontalBody x={6} y={26} w={52} h={12} />
      <line x1="0" y1="32" x2="6" y2="32" />
      <line x1="58" y1="32" x2="64" y2="32" />
      <path d="M 18,32 L 44,32 M 39,27 L 44,32 L 39,37" />
    </SymbolSvg>
  )
}

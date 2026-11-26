import { SymbolSvg } from './base'
import { HorizontalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Steam drum — horizontal drum with an internal water-level line and
// multiple downcomer/riser tube connections along the bottom.
export default function SteamDrum(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <HorizontalBody x={8} y={20} w={44} h={20} />
      <line x1="12" y1="34" x2="48" y2="34" strokeDasharray="2 2" />
      <line x1="20" y1="40" x2="20" y2="48" />
      <line x1="32" y1="40" x2="32" y2="48" />
      <line x1="44" y1="40" x2="44" y2="48" />
      <line x1="32" y1="16" x2="32" y2="20" />
      <line x1="2" y1="30" x2="8" y2="30" />
    </SymbolSvg>
  )
}

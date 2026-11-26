import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Double pipe exchanger — concentric inner tube inside an outer pipe
// (drawn as two parallel-wall pipes, one nested in the other) with an end
// return bend and process nozzles on the inner tube.
export default function DoublePipeHX(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="8" y1="20" x2="48" y2="20" />
      <line x1="8" y1="44" x2="48" y2="44" />
      <path d="M 48,20 A 12 12 0 0 1 48,44" />
      <line x1="8" y1="27" x2="42" y2="27" />
      <line x1="8" y1="37" x2="42" y2="37" />
      <path d="M 42,27 A 5 5 0 0 1 42,37" />
      <line x1="2" y1="27" x2="8" y2="27" />
      <line x1="2" y1="37" x2="8" y2="37" />
      <line x1="8" y1="20" x2="8" y2="14" />
      <line x1="8" y1="44" x2="8" y2="50" />
    </SymbolSvg>
  )
}

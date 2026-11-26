import { SymbolSvg } from './base'
import { HorizontalBody } from './primitives'
import type { PidSymbolProps } from './types'

// Horizontal pressure vessel — cylinder on two saddle supports, top nozzle.
export default function HorizontalVessel(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <HorizontalBody />
      <line x1="32" y1="22" x2="32" y2="14" />
      <line x1="20" y1="40" x2="20" y2="48" />
      <line x1="26" y1="40" x2="26" y2="48" />
      <line x1="18" y1="48" x2="28" y2="48" />
      <line x1="38" y1="40" x2="38" y2="48" />
      <line x1="44" y1="40" x2="44" y2="48" />
      <line x1="36" y1="48" x2="46" y2="48" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// On-page connector — plain circular reference bubble linking two points on
// the SAME drawing (vs. the pentagon Off-Page Connector, which already
// exists, for links to a DIFFERENT drawing).
export default function OnPageConnector(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="32" r="22" />
      <line x1="2" y1="32" x2="10" y2="32" />
      <line x1="54" y1="32" x2="62" y2="32" />
    </SymbolSvg>
  )
}

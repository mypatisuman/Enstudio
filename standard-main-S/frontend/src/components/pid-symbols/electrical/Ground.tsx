import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Ground / earth — standard descending-bars earth symbol.
export default function Ground(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="32" y1="8" x2="32" y2="30" />
      <line x1="18" y1="30" x2="46" y2="30" />
      <line x1="22" y1="38" x2="42" y2="38" />
      <line x1="26" y1="46" x2="38" y2="46" />
      <line x1="30" y1="54" x2="34" y2="54" />
    </SymbolSvg>
  )
}

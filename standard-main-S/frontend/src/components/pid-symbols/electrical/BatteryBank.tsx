import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Battery bank — series of alternating long/short cell plates (standard
// multi-cell battery symbol), with leads at both ends.
export default function BatteryBank(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="12" y2="32" />
      <line x1="12" y1="16" x2="12" y2="48" />
      <line x1="18" y1="22" x2="18" y2="42" />
      <line x1="24" y1="16" x2="24" y2="48" />
      <line x1="30" y1="22" x2="30" y2="42" />
      <line x1="36" y1="16" x2="36" y2="48" />
      <line x1="42" y1="22" x2="42" y2="42" />
      <line x1="48" y1="16" x2="48" y2="48" />
      <line x1="48" y1="32" x2="56" y2="32" />
    </SymbolSvg>
  )
}

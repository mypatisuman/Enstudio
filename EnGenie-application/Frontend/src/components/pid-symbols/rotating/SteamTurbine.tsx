import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Steam turbine — same tapered multi-stage casing as Turbine, plus a top
// steam-inlet nozzle and an exhaust flow arrow at the wide/low-pressure end.
export default function SteamTurbine(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 8,16 L 8,44 L 52,36 L 52,24 Z" />
      <line x1="16" y1="18" x2="16" y2="42" />
      <line x1="24" y1="19" x2="24" y2="41" />
      <line x1="32" y1="21" x2="32" y2="39" />
      <line x1="40" y1="23" x2="40" y2="37" />
      <line x1="16" y1="6" x2="16" y2="18" />
      <path d="M 52,30 L 60,30 M 56,26 L 60,30 L 56,34" />
    </SymbolSvg>
  )
}

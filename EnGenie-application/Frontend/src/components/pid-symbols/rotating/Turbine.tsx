import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Generic mechanical-drive turbine — tapered casing (wide inlet end,
// narrow exhaust end) with internal blade-stage lines and a through shaft.
// Simpler than SteamTurbine/GasTurbine (no boiler/combustor section).
export default function Turbine(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 8,16 L 8,44 L 52,36 L 52,24 Z" />
      <line x1="16" y1="18" x2="16" y2="42" />
      <line x1="24" y1="19" x2="24" y2="41" />
      <line x1="32" y1="21" x2="32" y2="39" />
      <line x1="40" y1="23" x2="40" y2="37" />
      <line x1="4" y1="30" x2="8" y2="30" />
      <line x1="52" y1="30" x2="58" y2="30" />
    </SymbolSvg>
  )
}

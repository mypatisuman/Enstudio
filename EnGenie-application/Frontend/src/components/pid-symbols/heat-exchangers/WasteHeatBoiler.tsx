import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Waste heat boiler — hot-gas duct shell with a diagonal-hatch tube bank
// (recovering heat from a gas stream, not fired) and a steam drum riding
// on top — the drum is what marks it apart from a plain HX shell.
export default function WasteHeatBoiler(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="24" cy="14" r="8" strokeDasharray="2 2" />
      <line x1="24" y1="22" x2="24" y2="28" />
      <rect x="10" y="28" width="44" height="26" />
      <path d="M 12,30 L 52,52 M 12,38 L 44,52 M 12,46 L 36,52 M 20,30 L 52,44" />
      <line x1="4" y1="41" x2="10" y2="41" />
      <line x1="54" y1="41" x2="60" y2="41" />
      <line x1="24" y1="2" x2="24" y2="6" />
    </SymbolSvg>
  )
}

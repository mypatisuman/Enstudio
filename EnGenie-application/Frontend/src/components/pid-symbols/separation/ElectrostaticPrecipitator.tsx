import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Electrostatic precipitator — rectangular housing with vertical collection
// plates, dashed high-voltage electrode wires between them, and a hopper
// (V-bottom) collecting the precipitated solids.
export default function ElectrostaticPrecipitator(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 10,10 L 54,10 L 54,40 L 40,54 L 24,54 L 10,40 Z" />
      <line x1="20" y1="12" x2="20" y2="40" />
      <line x1="32" y1="12" x2="32" y2="44" />
      <line x1="44" y1="12" x2="44" y2="40" />
      <line x1="26" y1="14" x2="26" y2="38" strokeDasharray="2 2" />
      <line x1="38" y1="14" x2="38" y2="38" strokeDasharray="2 2" />
      <line x1="2" y1="24" x2="10" y2="24" />
      <line x1="54" y1="24" x2="62" y2="24" />
      <line x1="32" y1="54" x2="32" y2="60" />
    </SymbolSvg>
  )
}

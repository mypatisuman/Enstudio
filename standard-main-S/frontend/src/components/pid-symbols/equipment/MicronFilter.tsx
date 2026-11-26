import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Micron filter — vertical cartridge filter housing (dished-head vessel,
// same ISO 10628 shell as the vessels library) with a dense cross-hatch
// cartridge element, inlet, outlet, and bottom drain.
export default function MicronFilter(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={20} y={10} w={24} h={40} capRy={8} />
      <path d="M 22,20 L 42,42 M 42,20 L 22,42 M 22,26 L 36,42 M 28,20 L 42,36 M 22,32 L 30,42 M 34,20 L 42,30" />
      <line x1="20" y1="24" x2="13" y2="24" />
      <line x1="44" y1="30" x2="51" y2="30" />
      <line x1="32" y1="2" x2="32" y2="10" />
      <line x1="32" y1="58" x2="32" y2="62" />
    </SymbolSvg>
  )
}

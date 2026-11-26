import { SymbolSvg } from './base'
import { VerticalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Boiler — vertical steam drum, dashed water level, heating coil at the
// bottom, steam outlet top, feedwater inlet side.
export default function Boiler(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <VerticalBody x={20} y={14} w={24} h={34} capRy={8} />
      <line x1="32" y1="6" x2="32" y2="1" />
      <line x1="22" y1="38" x2="42" y2="38" strokeDasharray="2 2" />
      <path d="M 22,48 Q 27,44 32,48 Q 37,44 42,48" />
      <line x1="20" y1="24" x2="13" y2="24" />
      <line x1="32" y1="56" x2="32" y2="62" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { Handwheel } from './primitives'
import type { PidSymbolProps } from './types'

// 3-way valve — three converging bowtie ports (two horizontal + one
// perpendicular) meeting at a common junction, manual handwheel actuator.
export default function ThreeWayValve(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <polygon points="4,16 4,48 32,32" />
      <polygon points="60,16 60,48 32,32" />
      <polygon points="20,56 44,56 32,32" />
      <line x1="0" y1="32" x2="4" y2="32" />
      <line x1="60" y1="32" x2="64" y2="32" />
      <line x1="32" y1="56" x2="32" y2="62" />
      <Handwheel />
    </SymbolSvg>
  )
}

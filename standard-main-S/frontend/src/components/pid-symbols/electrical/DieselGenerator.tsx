import { SymbolSvg } from './base'
import { MachineCircle } from './primitives'
import type { PidSymbolProps } from './types'

// Diesel generator — generator circle with a fuel-tank/skid base attached,
// marking it as an engine-driven package rather than a grid-tied generator.
export default function DieselGenerator(props: PidSymbolProps) {
  const color = props.stroke ?? '#F59E0B'
  return (
    <SymbolSvg {...props}>
      <MachineCircle letter="G" color={color} />
      <rect x="16" y="54" width="32" height="8" />
      <line x1="24" y1="50" x2="24" y2="54" />
      <line x1="40" y1="50" x2="40" y2="54" />
    </SymbolSvg>
  )
}

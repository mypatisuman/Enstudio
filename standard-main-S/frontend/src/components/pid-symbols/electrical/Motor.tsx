import { SymbolSvg } from './base'
import { MachineCircle } from './primitives'
import type { PidSymbolProps } from './types'

// Generic electric motor — IEC 60617 rotating-machine circle with "M".
export default function Motor(props: PidSymbolProps) {
  const color = props.stroke ?? '#F59E0B'
  return (
    <SymbolSvg {...props}>
      <MachineCircle letter="M" color={color} />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import { MachineCircle } from './primitives'
import type { PidSymbolProps } from './types'

// Generator — IEC 60617 rotating-machine circle with "G".
export default function Generator(props: PidSymbolProps) {
  const color = props.stroke ?? '#F59E0B'
  return (
    <SymbolSvg {...props}>
      <MachineCircle letter="G" color={color} />
    </SymbolSvg>
  )
}

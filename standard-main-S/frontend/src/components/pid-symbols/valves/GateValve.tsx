import { SymbolSvg } from './base'
import { BowtieBody, FlowLine } from './primitives'
import type { PidSymbolProps } from './types'

// Gate valve — bowtie body, gate wedge (parallel bars) at the throat, and
// a rising stem to a handwheel above (OS&Y convention). actuatorType='none'
// drops the visible stem/wheel for a non-rising-stem variant.
export default function GateValve({ actuatorType = 'manual', ...props }: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      <line x1="27" y1="20" x2="27" y2="44" />
      <line x1="37" y1="20" x2="37" y2="44" />
      {actuatorType !== 'none' && <>
        <line x1="32" y1="20" x2="32" y2="6" />
        <circle cx="32" cy="4" r="4" />
      </>}
    </SymbolSvg>
  )
}

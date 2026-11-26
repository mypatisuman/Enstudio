import { SymbolSvg } from './base'
import { BowtieBody, FlowLine, Handwheel } from './primitives'
import type { PidSymbolProps } from './types'

// Plug valve — bowtie body with a solid filled plug at the throat (the
// filled-dot convention ISA uses specifically for plug valves) and a
// handwheel actuator.
export default function PlugValve(props: PidSymbolProps) {
  const color = props.stroke ?? '#EAB308'
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      <Handwheel />
      <circle cx="32" cy="32" r="6" fill={color} />
    </SymbolSvg>
  )
}

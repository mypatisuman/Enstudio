import { SymbolSvg } from './base'
import { BowtieBody, FlowLine } from './primitives'
import type { PidSymbolProps } from './types'

// Normally closed valve — standard bowtie body with an internal fail-safe
// spring and the "NC" fail-position tag, per ISA actuator fail-state convention.
export default function NormallyClosedValve(props: PidSymbolProps) {
  const color = props.stroke ?? '#EAB308'
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      <path d="M 32,16 L 32,10 M 27,10 Q 32,6 37,10 Q 32,14 27,10 Q 32,6 37,10" />
      <text x="14" y="30" textAnchor="middle" dominantBaseline="central"
        fontSize="9" fontWeight="700" stroke="none" fill={color}>NC</text>
    </SymbolSvg>
  )
}

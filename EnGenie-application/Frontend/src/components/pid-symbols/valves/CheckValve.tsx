import { SymbolSvg } from './base'
import { BowtieBody, FlowLine } from './primitives'
import type { PidSymbolProps } from './types'

// Check valve — bowtie body with a hinged disc (small arc = hinge, angled
// line = disc) and the flow-direction arrow that distinguishes a check
// valve from every other 2-way valve in this library.
export default function CheckValve(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      <path d="M 22,24 A 6 6 0 0 1 22,40" />
      <line x1="22" y1="24" x2="34" y2="32" />
      <path d="M 40,32 L 50,32 M 45,27 L 50,32 L 45,37" />
    </SymbolSvg>
  )
}

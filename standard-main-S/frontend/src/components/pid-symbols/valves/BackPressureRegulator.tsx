import { SymbolSvg } from './base'
import { BowtieBody } from './primitives'
import type { PidSymbolProps } from './types'

// Back-pressure regulator — same dome/spring self-actuated body as
// PressureRegulatorPCV, but senses UPSTREAM pressure (dashed sense line on
// the inlet side) and the flow arrow reverses to show it throttles the
// upstream side, not the downstream — the two are mirror images of each
// other, matching how they're actually drawn differently on a P&ID.
export default function BackPressureRegulator(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <line x1="0" y1="32" x2="4" y2="32" />
      <path d="M 64,32 L 58,32 M 62,29 L 58,32 L 62,35" />
      <line x1="32" y1="16" x2="32" y2="10" />
      <path d="M 20,10 A 12 6 0 0 1 44,10" />
      <path d="M 38,10 L 38,4 M 34,4 Q 38,7 42,4 Q 46,7 34,2 Q 38,5 42,2" />
      <path d="M 20,10 L 14,10 L 14,32" strokeDasharray="2 2" />
    </SymbolSvg>
  )
}

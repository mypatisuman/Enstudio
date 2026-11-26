import { SymbolSvg } from './base'
import { BowtieBody } from './primitives'
import type { PidSymbolProps } from './types'

// Pressure regulator (PCV) — self-actuated spring/weight-loaded regulator
// (dome + spring, not a pneumatic diaphragm) sensing downstream pressure,
// with the flow arrow showing forward (reducing) service.
export default function PressureRegulatorPCV(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <path d="M 2,32 L 8,32 M 4,29 L 8,32 L 4,35" />
      <line x1="60" y1="32" x2="64" y2="32" />
      <line x1="32" y1="16" x2="32" y2="10" />
      <path d="M 20,10 A 12 6 0 0 1 44,10" />
      <path d="M 26,10 L 26,4 M 22,4 Q 26,7 30,4 Q 34,7 22,2 Q 26,5 30,2" />
      <path d="M 44,10 L 50,10 L 50,32" strokeDasharray="2 2" />
    </SymbolSvg>
  )
}

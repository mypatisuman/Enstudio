import { SymbolSvg } from './base'
import { BowtieBody, FlowLine } from '../valves/primitives'
import type { PidSymbolProps } from './types'

// Deluge valve — standard valve bowtie body with a trip/actuator trim on
// top (electric or pneumatic release), per fire-protection P&ID convention.
export default function DelugeValve(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <BowtieBody />
      <FlowLine />
      <rect x="26" y="6" width="12" height="10" />
      <line x1="32" y1="16" x2="32" y2="20" />
    </SymbolSvg>
  )
}

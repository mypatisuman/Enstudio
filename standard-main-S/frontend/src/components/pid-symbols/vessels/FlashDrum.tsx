import { SymbolSvg } from './base'
import { VerticalBody, HorizontalBody } from './primitives'
import type { PidSymbolProps } from './types'

// Flash drum — standard vessel geometry (per ISA convention, same outline as
// VerticalVessel/HorizontalVessel), distinguished only by nozzle function:
// side feed inlet, top vapor outlet, bottom liquid outlet/drain.
export default function FlashDrum({ orientation = 'vertical', ...props }:
  PidSymbolProps & { orientation?: 'vertical' | 'horizontal' }) {
  if (orientation === 'horizontal') {
    return (
      <SymbolSvg {...props}>
        <HorizontalBody />
        <line x1="32" y1="22" x2="32" y2="14" />
      </SymbolSvg>
    )
  }
  return (
    <SymbolSvg {...props}>
      <VerticalBody />
      <line x1="32" y1="10" x2="32" y2="3" />
      <line x1="32" y1="54" x2="32" y2="61" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Double-wall tank — inner tank + outer secondary-containment shell with a
// plain insulation/containment gap (no vacuum hatching — see CryogenicTank).
export default function DoubleWallTank(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="12" y="14" width="40" height="40" />
      <rect x="19" y="21" width="26" height="26" />
      <line x1="24" y1="10" x2="24" y2="14" />
      <line x1="40" y1="10" x2="40" y2="14" />
      <line x1="22" y1="10" x2="42" y2="10" />
      <line x1="32" y1="54" x2="32" y2="60" />
      <line x1="52" y1="34" x2="58" y2="34" />
    </SymbolSvg>
  )
}

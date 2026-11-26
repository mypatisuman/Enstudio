import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Cable tray — ladder-tray cross-section (two rails + rungs), the standard
// perspective used for tray runs on electrical/instrument drawings.
export default function CableTray(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="22" x2="60" y2="22" />
      <line x1="4" y1="34" x2="60" y2="34" />
      <line x1="12" y1="22" x2="12" y2="34" />
      <line x1="22" y1="22" x2="22" y2="34" />
      <line x1="32" y1="22" x2="32" y2="34" />
      <line x1="42" y1="22" x2="42" y2="34" />
      <line x1="52" y1="22" x2="52" y2="34" />
    </SymbolSvg>
  )
}

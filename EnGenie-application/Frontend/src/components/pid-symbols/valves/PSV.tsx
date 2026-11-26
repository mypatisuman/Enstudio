import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Pressure safety valve (PSV/PRV/SRV) — API 526 silhouette: rectangular
// body block (NOT the generic bowtie — a PSV body is a distinct casting),
// spring housing with zigzag spring on top, bottom inlet, side outlet bent
// away from the body (relief discharge routing).
export default function PSV(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="22" y="30" width="20" height="16" />
      <line x1="32" y1="46" x2="32" y2="58" />
      <path d="M 42,36 L 52,36 M 47,31 L 52,36 L 47,41" />
      <rect x="26" y="14" width="12" height="16" />
      <path d="M 26,16 Q 32,20 38,16 Q 32,22 26,18 Q 32,24 38,20" />
    </SymbolSvg>
  )
}

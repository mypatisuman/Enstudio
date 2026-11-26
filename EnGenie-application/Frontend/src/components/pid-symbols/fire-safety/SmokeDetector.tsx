import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Smoke detector — ceiling-mount dome with drifting smoke-particle dots.
export default function SmokeDetector(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 16,24 A 16 16 0 0 1 48,24 Z" />
      <line x1="16" y1="24" x2="48" y2="24" />
      <circle cx="26" cy="34" r="1.4" />
      <circle cx="32" cy="38" r="1.4" />
      <circle cx="38" cy="34" r="1.4" />
      <circle cx="30" cy="30" r="1.4" />
    </SymbolSvg>
  )
}

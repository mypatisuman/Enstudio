import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Transducer (TY/FY) — instrument bubble plus the small output-element
// square below it (converts the signal to a pneumatic/electric output),
// distinguishing it from a plain measurement bubble.
export default function Transducer({ tagText = 'TY', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#0EA5E9'
  return (
    <SymbolSvg {...props} fallback="#0EA5E9">
      <line x1="2" y1="26" x2="14" y2="26" />
      <line x1="50" y1="26" x2="62" y2="26" />
      <circle cx="32" cy="26" r="16" />
      <text x="32" y="26" textAnchor="middle" dominantBaseline="central"
        fontSize="9" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
      <line x1="32" y1="42" x2="32" y2="48" />
      <rect x="27" y="48" width="10" height="10" />
    </SymbolSvg>
  )
}

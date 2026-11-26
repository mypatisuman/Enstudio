import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Auto/Manual selector switch — horizontal AUTO/MAN selector bar with a
// pointer knob, not an instrument bubble at all; this is a distinct
// field-station control device.
export default function AutoManualSelector(props: PidSymbolProps) {
  const color = props.stroke ?? '#94A3B8'
  return (
    <SymbolSvg {...props} fallback="#94A3B8">
      <line x1="4" y1="34" x2="24" y2="34" />
      <line x1="42" y1="34" x2="60" y2="34" />
      <circle cx="32" cy="34" r="10" />
      <path d="M 32,34 L 40,26 M 36,26 L 40,26 L 40,30" />
      <text x="14" y="48" textAnchor="middle" dominantBaseline="central"
        fontSize="8" fontWeight="700" stroke="none" fill={color}>AUTO</text>
      <text x="50" y="48" textAnchor="middle" dominantBaseline="central"
        fontSize="8" fontWeight="700" stroke="none" fill={color}>MAN</text>
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Alarm (OA) — instrument bubble with radiating sunburst ticks (the
// annunciator/alarm convention), distinguishing it from a plain measurement
// bubble at a glance.
export default function Alarm({ tagText = 'OA', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#F59E0B'
  return (
    <SymbolSvg {...props} fallback="#F59E0B">
      <line x1="2" y1="32" x2="14" y2="32" />
      <line x1="50" y1="32" x2="62" y2="32" />
      <path d="M 32,10 L 32,4 M 46,16 L 51,11 M 52,32 L 58,32 M 46,48 L 51,53 M 18,16 L 13,11 M 18,48 L 13,53"
        strokeDasharray="0" />
      <circle cx="32" cy="32" r="18" />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="11" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

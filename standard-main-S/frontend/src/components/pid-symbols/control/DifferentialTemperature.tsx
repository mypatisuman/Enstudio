import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Differential temperature (TD) — plain field-mounted ISA bubble.
export default function DifferentialTemperature({ tagText = 'TD', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#EF4444'
  return (
    <SymbolSvg {...props} fallback="#EF4444">
      <line x1="2" y1="32" x2="14" y2="32" />
      <line x1="50" y1="32" x2="62" y2="32" />
      <circle cx="32" cy="32" r="18" />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="11" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

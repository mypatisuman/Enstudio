import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Mass flow meter (MFM) — plain field-mounted ISA bubble, same convention
// as the switch bubbles, just a different function tag.
export default function MassFlowMeter({ tagText = 'MFM', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#0EA5E9'
  return (
    <SymbolSvg {...props} fallback="#0EA5E9">
      <line x1="2" y1="32" x2="14" y2="32" />
      <line x1="50" y1="32" x2="62" y2="32" />
      <circle cx="32" cy="32" r="18" />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="10" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

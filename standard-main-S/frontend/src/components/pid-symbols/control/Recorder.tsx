import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Recorder — instrument bubble with dashed process-connection leads by
// default (historical/logged-value convention); mountingStyle="computer"
// dashes the bubble outline itself for a software-recorder variant.
export default function Recorder({ tagText = 'R', mountingStyle = 'field', ...props }: PidSymbolProps) {
  const dashedCircle = mountingStyle === 'computer'
  const textColor = props.stroke ?? '#94A3B8'
  return (
    <SymbolSvg {...props} fallback="#94A3B8">
      <line x1="2" y1="32" x2="14" y2="32" strokeDasharray="3 2" />
      <line x1="50" y1="32" x2="62" y2="32" strokeDasharray="3 2" />
      <circle cx="32" cy="32" r="18" strokeDasharray={dashedCircle ? '4 3' : undefined} />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="13" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

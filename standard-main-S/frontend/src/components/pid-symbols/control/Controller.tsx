import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Controller (FIC) — ISA S5.1 instrument bubble. mountingStyle drives the
// standard ISA line convention: solid circle = field, circle + horizontal
// line = panel-mounted, dashed circle = computer function, circle + dashed
// line = shared display.
export default function Controller({ tagText = 'FIC', mountingStyle = 'panel', ...props }: PidSymbolProps) {
  const dashedCircle = mountingStyle === 'computer'
  const line = mountingStyle === 'panel' || mountingStyle === 'shared'
  const dashedLine = mountingStyle === 'shared'
  const textColor = props.stroke ?? '#0EA5E9'
  return (
    <SymbolSvg {...props} fallback="#0EA5E9">
      <line x1="2" y1="32" x2="14" y2="32" />
      <line x1="50" y1="32" x2="62" y2="32" />
      <circle cx="32" cy="32" r="18" strokeDasharray={dashedCircle ? '4 3' : undefined} />
      {line && <line x1="14" y1="32" x2="50" y2="32" strokeDasharray={dashedLine ? '3 2' : undefined} />}
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="12" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

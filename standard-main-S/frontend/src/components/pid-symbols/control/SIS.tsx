import { SymbolSvg } from './base'
import { SystemBox } from './primitives'
import type { PidSymbolProps } from './types'

// SIS — same dashed system box as DCS/PLC, but safety-red by default so it
// reads as functionally distinct at a glance (independent safety layer).
export default function SIS({ tagText = 'SIS', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#F43F5E'
  return (
    <SymbolSvg {...props} fallback="#F43F5E">
      <SystemBox />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="10" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

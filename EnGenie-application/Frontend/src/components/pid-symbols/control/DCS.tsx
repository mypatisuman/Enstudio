import { SymbolSvg } from './base'
import { SystemBox } from './primitives'
import type { PidSymbolProps } from './types'

// DCS — dashed computer-function rectangle (distributed control node).
export default function DCS({ tagText = 'DCS', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#06B6D4'
  return (
    <SymbolSvg {...props} fallback="#06B6D4">
      <SystemBox />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="10" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

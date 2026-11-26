import { SymbolSvg } from './base'
import { SystemBox } from './primitives'
import type { PidSymbolProps } from './types'

// PLC — dashed computer-function rectangle + I/O port ticks on all four
// edges, giving it the "modular rack" look that distinguishes it from DCS.
export default function PLC({ tagText = 'PLC', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#06B6D4'
  return (
    <SymbolSvg {...props} fallback="#06B6D4">
      <SystemBox ports />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="10" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

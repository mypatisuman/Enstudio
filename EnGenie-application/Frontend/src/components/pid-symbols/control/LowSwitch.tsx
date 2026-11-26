import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Low switch — same ISA bubble as HighSwitch; only the default tag differs
// (LSL/PSL/TSL/FSL/ASL — configurable via tagText).
export default function LowSwitch({ tagText = 'LS', ...props }: PidSymbolProps) {
  const textColor = props.stroke ?? '#F59E0B'
  return (
    <SymbolSvg {...props} fallback="#F59E0B">
      <line x1="2" y1="32" x2="14" y2="32" />
      <line x1="50" y1="32" x2="62" y2="32" />
      <circle cx="32" cy="32" r="18" />
      <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
        fontSize="12" fontWeight="700" stroke="none" fill={textColor}>{tagText}</text>
    </SymbolSvg>
  )
}

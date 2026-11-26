import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

const DASH: Record<string, string | undefined> = {
  solid: undefined,
  dashed: '6 3',
  'dash-dot': '8 3 2 3',
  'dash-dot-dot': '8 3 2 3 2 3',
}

// Generic utility service line — per ISA/ISO 10628 convention, utility
// services (cooling water, nitrogen, instrument air, caustic, etc.) are NOT
// distinct equipment shapes; they're an ordinary line distinguished by a
// line-type code and a service tag. This one component covers all of them
// via `serviceCode` (the tag text, e.g. "N2", "IA", "CW") and `lineStyle`
// (the ISA line-type dash pattern) instead of inventing fake per-service icons.
export default function UtilityLine({ serviceCode = '', lineStyle = 'solid', ...props }:
  PidSymbolProps & { serviceCode?: string; lineStyle?: keyof typeof DASH }) {
  const color = props.stroke ?? '#38BDF8'
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="60" y2="32" strokeDasharray={DASH[lineStyle]} />
      {serviceCode && <>
        <rect x="20" y="24" width="24" height="16" fill="#0B1220" />
        <text x="32" y="32" textAnchor="middle" dominantBaseline="central"
          fontSize="9" fontWeight="700" stroke="none" fill={color}>{serviceCode}</text>
      </>}
    </SymbolSvg>
  )
}

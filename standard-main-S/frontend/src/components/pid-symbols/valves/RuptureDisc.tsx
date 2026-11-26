import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Rupture disc — burst membrane set into a straight pipe spool: centerline
// through, a dome (or inverted dome for the reverse-buckling variant) at
// the disc location, and holder flanges either side.
export default function RuptureDisc({ valveState = 'open', ...props }: PidSymbolProps) {
  const reverseBuckling = valveState === 'closed'
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="60" y2="32" />
      <line x1="24" y1="24" x2="24" y2="40" />
      <line x1="40" y1="24" x2="40" y2="40" />
      <path d={reverseBuckling ? 'M 24,24 Q 32,32 40,24' : 'M 24,32 Q 32,20 40,32'} />
    </SymbolSvg>
  )
}

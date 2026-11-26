import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Spherical pressure vessel — true sphere on support legs, top/bottom/side
// nozzles, equatorial seam line (ISO 10628 spherical-tank convention).
export default function SphericalVessel(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="32" r="22" />
      <line x1="10" y1="32" x2="54" y2="32" strokeDasharray="3 2" />
      <line x1="32" y1="10" x2="32" y2="3" />
      <line x1="32" y1="54" x2="32" y2="61" />
      <line x1="54" y1="32" x2="60" y2="32" />
      <line x1="16" y1="48" x2="10" y2="60" />
      <line x1="48" y1="48" x2="54" y2="60" />
    </SymbolSvg>
  )
}

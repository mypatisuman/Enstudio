import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Horton sphere — elevated spherical storage vessel on a leg cluster with a
// horizontal ring brace (distinct from SphericalVessel's short skirt legs —
// a Horton sphere is elevated well clear of grade on a tall support frame).
export default function HortonSphere(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="24" r="18" />
      <line x1="14" y1="24" x2="50" y2="24" strokeDasharray="3 2" />
      <line x1="32" y1="6" x2="32" y2="1" />
      <line x1="50" y1="24" x2="56" y2="24" />
      <line x1="20" y1="38" x2="12" y2="60" />
      <line x1="44" y1="38" x2="52" y2="60" />
      <line x1="24" y1="34" x2="18" y2="60" />
      <line x1="40" y1="34" x2="46" y2="60" />
      <line x1="14" y1="48" x2="50" y2="48" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

type Roof = 'flat' | 'cone' | 'dome' | 'floating' | 'internal_floating'

// Atmospheric storage tank — flat bottom on grade, vertical shell. Roof
// style is swappable without touching the shell, per ISA storage-tank
// convention. 'floating' is a true open-top tank (no fixed roof — the
// pontoon deck itself closes the top); 'internal_floating' keeps a fixed
// roof line with the floating deck riding inside it (IFRT).
export default function AtmosphericTank({ roof = 'flat', ...props }:
  PidSymbolProps & { roof?: Roof }) {
  const shellTop = roof === 'cone' ? 18 : roof === 'dome' ? 16 : 12
  return (
    <SymbolSvg {...props}>
      {/* Shell — flat bottom, straight sides */}
      <path d={`M 16,${shellTop} L 16,54 L 48,54 L 48,${shellTop}`} />
      {/* Grade line */}
      <line x1="10" y1="54" x2="54" y2="54" />
      {/* Roof */}
      {roof === 'flat' && <line x1="16" y1="12" x2="48" y2="12" />}
      {roof === 'cone' && <path d="M 16,18 L 32,4 L 48,18" />}
      {roof === 'dome' && <path d="M 16,16 Q 32,4 48,16" />}
      {roof === 'internal_floating' && (
        <>
          <line x1="16" y1="12" x2="48" y2="12" />
          <path d="M 20,26 L 24,22 L 28,26 M 30,26 L 34,22 L 38,26 M 40,26 L 44,22" />
        </>
      )}
      {roof === 'floating' && (
        <>
          <path d="M 16,20 L 20,16 L 44,16 L 48,20" />
          <line x1="16" y1="28" x2="48" y2="28" strokeDasharray="2 2" />
        </>
      )}
    </SymbolSvg>
  )
}

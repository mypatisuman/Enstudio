import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Spiral heat exchanger — circular housing with a true wound spiral
// passage (concentric-but-connected coil, not a plain circle), two
// process nozzles.
export default function SpiralHX(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="32" r="24" />
      <path d="M 32,32 m 0,-16 a 16 16 0 0 1 16,16 a 12 12 0 0 1 -12,12 a 8 8 0 0 1 -8,-8 a 4 4 0 0 1 4,-4" />
      <line x1="8" y1="32" x2="2" y2="32" />
      <line x1="56" y1="32" x2="62" y2="32" />
    </SymbolSvg>
  )
}

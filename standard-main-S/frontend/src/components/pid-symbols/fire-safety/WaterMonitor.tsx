import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Water monitor (monitor nozzle) — swivel base on a riser with an
// adjustable-aim nozzle barrel, per fire-water monitor convention.
export default function WaterMonitor(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="16" y1="58" x2="48" y2="58" />
      <line x1="32" y1="58" x2="32" y2="36" />
      <circle cx="32" cy="32" r="5" />
      <path d="M 36,28 L 54,20 M 50,18 L 54,20 L 52,24" />
    </SymbolSvg>
  )
}

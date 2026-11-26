import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Reboiler — same shell-and-tube body language as Condenser (a kettle
// reboiler IS a shell-and-tube variant) but distinguished by a diagonal
// vapor-outlet nozzle (kettle vapor space) instead of a straight top nozzle,
// and heating-medium flow arrows instead of a plain cooling-water line.
export default function Reboiler(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="32" r="22" />
      <path d="M 14,32 Q 20,20 26,32 T 38,32 T 50,32" />
      <path d="M 40,14 L 46,8 M 43,8 L 46,8 L 46,11" />
      <line x1="32" y1="54" x2="32" y2="61" />
      <path d="M 4,32 L 10,32 M 8,29 L 10,32 L 8,35" />
      <path d="M 60,32 L 54,32 M 56,29 L 54,32 L 56,35" />
    </SymbolSvg>
  )
}

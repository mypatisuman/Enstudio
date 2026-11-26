import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Condenser — circular body, internal coil, vapor inlet TOP, condensate
// outlet BOTTOM, cooling water straight through LEFT→RIGHT.
export default function Condenser(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="32" r="22" />
      <path d="M 14,32 Q 20,20 26,32 T 38,32 T 50,32" />
      <line x1="32" y1="10" x2="32" y2="3" />
      <line x1="32" y1="54" x2="32" y2="61" />
      <path d="M 4,32 L 10,32 M 8,29 L 10,32 L 8,35" />
      <line x1="54" y1="32" x2="60" y2="32" />
    </SymbolSvg>
  )
}

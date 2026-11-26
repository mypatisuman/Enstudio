import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Filter — housing with a pleated (zigzag) filter-media element, not just a
// dashed line, so it reads as an actual filter cartridge.
export default function Filter(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="12" y="18" width="40" height="28" />
      <path d="M 20,18 L 24,46 L 28,18 L 32,46 L 36,18 L 40,46 L 44,18" />
      <line x1="4" y1="32" x2="12" y2="32" />
      <line x1="52" y1="32" x2="60" y2="32" />
    </SymbolSvg>
  )
}

import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Fuse — standard oval-on-a-line fuse symbol.
export default function Fuse(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="32" y1="4" x2="32" y2="20" />
      <rect x="24" y="20" width="16" height="24" rx="8" />
      <line x1="32" y1="44" x2="32" y2="60" />
    </SymbolSvg>
  )
}

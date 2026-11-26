import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Steam trap — small in-line housing with an internal float/disc mechanism
// on the drain line, per standard steam-trap P&ID convention.
export default function SteamTrap(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="4" y1="32" x2="20" y2="32" />
      <rect x="20" y="20" width="24" height="24" />
      <circle cx="32" cy="32" r="6" />
      <line x1="44" y1="32" x2="60" y2="32" />
    </SymbolSvg>
  )
}

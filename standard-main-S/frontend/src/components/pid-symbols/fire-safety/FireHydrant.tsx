import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Fire hydrant — classic hydrant silhouette: body, cap nut, two side hose
// outlet nozzles, base flange to the underground main.
export default function FireHydrant(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="26" y="4" width="12" height="8" />
      <path d="M 24,12 L 40,12 L 38,44 L 26,44 Z" />
      <line x1="14" y1="22" x2="24" y2="22" />
      <circle cx="12" cy="22" r="3" />
      <line x1="40" y1="22" x2="50" y2="22" />
      <circle cx="52" cy="22" r="3" />
      <line x1="20" y1="44" x2="44" y2="44" />
      <line x1="16" y1="50" x2="48" y2="50" />
    </SymbolSvg>
  )
}

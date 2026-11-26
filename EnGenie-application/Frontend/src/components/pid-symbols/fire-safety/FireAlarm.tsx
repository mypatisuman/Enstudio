import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Fire alarm (sounder/bell) — classic alarm-bell dome with clapper.
export default function FireAlarm(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <path d="M 16,38 A 16 16 0 0 1 48,38 L 48,42 L 16,42 Z" />
      <line x1="12" y1="42" x2="52" y2="42" />
      <circle cx="32" cy="48" r="3" />
      <line x1="32" y1="16" x2="32" y2="22" />
    </SymbolSvg>
  )
}

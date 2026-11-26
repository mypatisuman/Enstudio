import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Disconnect switch — standard open-blade isolator symbol on a line.
export default function DisconnectSwitch(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <line x1="32" y1="6" x2="32" y2="26" />
      <line x1="32" y1="26" x2="46" y2="14" />
      <circle cx="32" cy="26" r="2" />
      <circle cx="32" cy="42" r="2" />
      <line x1="32" y1="44" x2="32" y2="58" />
    </SymbolSvg>
  )
}

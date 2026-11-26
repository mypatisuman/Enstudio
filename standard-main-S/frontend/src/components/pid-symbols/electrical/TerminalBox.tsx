import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Terminal box — box with a row of individual terminal points (numbered
// terminal strip), distinct from JunctionBox's plain crossed box.
export default function TerminalBox(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="10" y="20" width="44" height="24" />
      {[18, 26, 34, 42, 50].map(x => <circle key={x} cx={x} cy="32" r="2" />)}
      <line x1="32" y1="10" x2="32" y2="20" />
    </SymbolSvg>
  )
}

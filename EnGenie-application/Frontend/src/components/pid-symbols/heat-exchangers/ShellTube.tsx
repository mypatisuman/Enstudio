import { SymbolSvg } from './base'
import { HorizontalBody } from '../vessels/primitives'
import type { PidSymbolProps } from './types'

// Shell & tube — horizontal shell, parallel internal tube lines, four
// nozzles (shell-side left/right + channel-side top/bottom), two saddles.
export default function ShellTube(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <HorizontalBody x={8} y={20} w={48} h={24} />
      {[24, 28, 32, 36, 40].map(y => <line key={y} x1="14" y1={y} x2="50" y2={y} />)}
      <line x1="20" y1="20" x2="20" y2="13" />
      <line x1="44" y1="44" x2="44" y2="51" />
      <line x1="2" y1="32" x2="8" y2="32" />
      <line x1="56" y1="32" x2="62" y2="32" />
      {/* Saddle supports */}
      <line x1="20" y1="44" x2="20" y2="50" />
      <line x1="26" y1="44" x2="26" y2="50" />
      <line x1="18" y1="50" x2="28" y2="50" />
      <line x1="38" y1="44" x2="38" y2="50" />
      <line x1="44" y1="44" x2="44" y2="50" />
      <line x1="36" y1="50" x2="46" y2="50" />
    </SymbolSvg>
  )
}

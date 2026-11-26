import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Mixer / agitator — motor + shaft + bowtie impeller mounted inside an
// open-top vessel outline, with a rotation arrow at the drive end.
export default function Mixer(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="27" y="2" width="10" height="8" />
      <path d="M 21,4 A 6 6 0 0 0 21,10" />
      <path d="M 21,4 L 18,4 L 20,7 Z" />
      <line x1="32" y1="10" x2="32" y2="46" />
      <path d="M 26,42 L 32,46 L 26,50 Z M 38,42 L 32,46 L 38,50 Z" />
      <path d="M 12,20 L 12,52 Q 12,58 18,58 L 46,58 Q 52,58 52,52 L 52,20" />
    </SymbolSvg>
  )
}

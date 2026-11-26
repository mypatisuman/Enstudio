import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Emergency lighting — same luminaire as LightingFixture, plus the small
// battery-backup mark that distinguishes emergency/standby fixtures.
export default function EmergencyLighting(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <circle cx="32" cy="34" r="14" />
      <line x1="14" y1="34" x2="20" y2="34" />
      <line x1="44" y1="34" x2="50" y2="34" />
      <line x1="20" y1="22" x2="24" y2="26" />
      <line x1="44" y1="22" x2="40" y2="26" />
      <line x1="20" y1="46" x2="24" y2="42" />
      <line x1="44" y1="46" x2="40" y2="42" />
      <line x1="32" y1="8" x2="32" y2="14" />
      <line x1="27" y1="30" x2="27" y2="38" />
      <line x1="24" y1="32" x2="24" y2="36" />
      <line x1="37" y1="30" x2="37" y2="38" />
      <line x1="40" y1="32" x2="40" y2="36" />
    </SymbolSvg>
  )
}

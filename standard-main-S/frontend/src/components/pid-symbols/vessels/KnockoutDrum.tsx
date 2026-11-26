import HorizontalVessel from './HorizontalVessel'
import type { PidSymbolProps } from './types'

// KO drum uses the exact same vessel outline as HorizontalVessel — per ISA
// convention it's distinguished only by tag/metadata, not by geometry.
export default function KnockoutDrum(props: PidSymbolProps) {
  return <HorizontalVessel {...props} />
}

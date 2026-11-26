import HorizontalVessel from './HorizontalVessel'
import type { PidSymbolProps } from './types'

// Horizontal storage tank ("bullet tank") — same outline as HorizontalVessel;
// per ISO 10628 it's a storage-service tag on the identical horizontal
// cylinder-on-saddles geometry, not a different shape.
export default function BulletTank(props: PidSymbolProps) {
  return <HorizontalVessel {...props} />
}

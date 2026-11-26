import TrayColumn from './TrayColumn'
import type { PidSymbolProps } from './types'

// Stabilizer column — same tray-column outline (service name, not a new shape).
export default function StabilizerColumn(props: PidSymbolProps) {
  return <TrayColumn {...props} />
}

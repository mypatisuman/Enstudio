import TrayColumn from './TrayColumn'
import type { PidSymbolProps } from './types'

// Deethanizer — same tray-column outline (service name, not a new shape).
export default function Deethanizer(props: PidSymbolProps) {
  return <TrayColumn {...props} />
}

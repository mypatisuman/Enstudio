import TrayColumn from './TrayColumn'
import type { PidSymbolProps } from './types'

// Debutanizer — same tray-column outline (service name, not a new shape).
export default function Debutanizer(props: PidSymbolProps) {
  return <TrayColumn {...props} />
}

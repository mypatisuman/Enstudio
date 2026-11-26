import TrayColumn from './TrayColumn'
import type { PidSymbolProps } from './types'

// Fractionator — same tray-column outline (service name, not a new shape).
export default function Fractionator(props: PidSymbolProps) {
  return <TrayColumn {...props} />
}

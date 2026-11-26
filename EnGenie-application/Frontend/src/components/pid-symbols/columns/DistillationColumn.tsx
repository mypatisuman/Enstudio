import TrayColumn from './TrayColumn'
import type { PidSymbolProps } from './types'

// Distillation column — same tray-column outline; per ISO 10628 the process
// service is carried by the tag, not a distinct shape.
export default function DistillationColumn(props: PidSymbolProps) {
  return <TrayColumn {...props} />
}

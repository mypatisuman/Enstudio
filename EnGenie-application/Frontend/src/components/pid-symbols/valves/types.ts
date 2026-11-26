export interface PidSymbolProps {
  width?: number
  height?: number
  stroke?: string
  strokeWidth?: number
  selected?: boolean
  hovered?: boolean
  className?: string
  rotation?: number
  actuatorType?: 'diaphragm' | 'manual' | 'none'
  valveState?: 'open' | 'closed'
}

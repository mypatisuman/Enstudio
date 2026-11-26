// Shared prop contract for every P&ID vessel symbol. Kept minimal — only
// what's needed today (size, color, selection state) plus the hooks callers
// will want once nodes support rotation/resizing/export (kind/className).
export interface PidSymbolProps {
  width?: number
  height?: number
  stroke?: string
  strokeWidth?: number
  selected?: boolean
  hovered?: boolean
  className?: string
}

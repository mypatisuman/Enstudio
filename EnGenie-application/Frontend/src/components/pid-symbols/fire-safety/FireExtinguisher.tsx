import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Fire extinguisher — classic cylinder-with-handle-and-hose silhouette.
export default function FireExtinguisher(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="22" y="18" width="20" height="34" rx="4" />
      <line x1="27" y1="18" x2="27" y2="12" />
      <line x1="37" y1="18" x2="37" y2="12" />
      <line x1="24" y1="12" x2="40" y2="12" />
      <path d="M 32,8 L 32,12" />
      <path d="M 22,20 L 12,26 L 12,32" />
    </SymbolSvg>
  )
}

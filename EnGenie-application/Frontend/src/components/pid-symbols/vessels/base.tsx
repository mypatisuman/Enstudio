import type { ReactNode } from 'react'
import type { PidSymbolProps } from './types'

// Default palette per the P&ID symbol spec — deliberately separate from the
// app's Theme (components/canvas/theme.ts) so this library stays reusable
// outside the canvas (export, print preview, etc).
export const PID_STROKE = {
  default: '#3B82F6',
  hover: '#60A5FA',
  selected: '#93C5FD',
} as const

export function resolveStroke({ stroke, selected, hovered }: PidSymbolProps): string {
  if (selected) return PID_STROKE.selected
  if (hovered) return PID_STROKE.hover
  return stroke ?? PID_STROKE.default
}

// Every symbol shares one 64×64 canvas so the whole set has an identical
// bounding box regardless of the equipment's real aspect ratio (same
// convention as Lucide/Feather icons) — this is what makes them line up in
// a palette or toolbar. Stroke-only, no fills, rounded joins throughout.
export function SymbolSvg({ width = 64, height = 64, strokeWidth = 2, className, children, ...rest }:
  PidSymbolProps & { children: ReactNode }) {
  return (
    <svg width={width} height={height} viewBox="0 0 64 64" className={className}
      xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={resolveStroke(rest)} strokeWidth={strokeWidth}
        strokeLinecap="round" strokeLinejoin="round">
        {children}
      </g>
    </svg>
  )
}

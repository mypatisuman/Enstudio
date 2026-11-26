import type { ReactNode } from 'react'
import type { PidSymbolProps } from './types'

export const PID_STROKE = { default: '#EF4444', hover: '#F87171', selected: '#FCA5A5' } as const

export function resolveStroke({ stroke, selected, hovered }: PidSymbolProps): string {
  if (selected) return PID_STROKE.selected
  if (hovered) return PID_STROKE.hover
  return stroke ?? PID_STROKE.default
}

export function SymbolSvg({ width = 64, height = 64, strokeWidth = 2, className, rotation, children, ...rest }:
  PidSymbolProps & { children: ReactNode }) {
  return (
    <svg width={width} height={height} viewBox="0 0 64 64" className={className}
      xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={resolveStroke(rest)} strokeWidth={strokeWidth}
        strokeLinecap="round" strokeLinejoin="round"
        transform={rotation ? `rotate(${rotation} 32 32)` : undefined}>
        {children}
      </g>
    </svg>
  )
}

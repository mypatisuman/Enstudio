import type { ReactNode } from 'react'
import type { PidSymbolProps } from './types'

export const PID_STROKE = { default: '#EAB308', hover: '#FCD34D', selected: '#EAB308' } as const

export function resolveStroke({ stroke, hovered }: PidSymbolProps): string {
  if (hovered) return PID_STROKE.hover
  return stroke ?? PID_STROKE.default
}

export function SymbolSvg({ width = 64, height = 64, strokeWidth = 2, className, rotation, selected, children, ...rest }:
  PidSymbolProps & { children: ReactNode }) {
  return (
    <svg width={width} height={height} viewBox="0 0 64 64" className={className}
      xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={resolveStroke(rest)} strokeWidth={selected ? 2.5 : strokeWidth}
        strokeLinecap="round" strokeLinejoin="round"
        transform={rotation ? `rotate(${rotation} 32 32)` : undefined}>
        {children}
      </g>
    </svg>
  )
}

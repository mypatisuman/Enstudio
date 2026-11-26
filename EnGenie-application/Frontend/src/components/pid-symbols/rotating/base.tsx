import type { ReactNode } from 'react'
import type { PidSymbolProps } from './types'

// Pump/mixer default; compressor & blower components override with '#6366F1'
// at the call site (per spec, compressors get their own stroke color even
// though they live in the same "rotating equipment" folder).
export const PID_STROKE = { default: '#22C55E', hover: '#4ADE80', selected: '#86EFAC' } as const

export function resolveStroke({ stroke, selected, hovered }: PidSymbolProps): string {
  if (selected) return PID_STROKE.selected
  if (hovered) return PID_STROKE.hover
  return stroke ?? PID_STROKE.default
}

export function SymbolSvg({ width = 64, height = 64, strokeWidth = 2, className, rotation, selected, children, ...rest }:
  PidSymbolProps & { children: ReactNode }) {
  return (
    <svg width={width} height={height} viewBox="0 0 64 64" className={className}
      xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={resolveStroke({ ...rest, selected })} strokeWidth={selected ? 2.5 : strokeWidth}
        strokeLinecap="round" strokeLinejoin="round"
        transform={rotation ? `rotate(${rotation} 32 32)` : undefined}>
        {children}
      </g>
    </svg>
  )
}

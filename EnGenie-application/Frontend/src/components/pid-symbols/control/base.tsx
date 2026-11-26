import type { ReactNode } from 'react'
import type { PidSymbolProps } from './types'

// Per-instrument-type default; each component passes its own default via
// the `stroke` prop at the call site (Controller=#0EA5E9, Recorder=#94A3B8,
// switches=#F59E0B, PLC/DCS=#06B6D4, SIS=#F43F5E).
export function resolveStroke({ stroke, hovered, fallback }: PidSymbolProps & { fallback: string }): string {
  if (hovered) return lighten(stroke ?? fallback)
  return stroke ?? fallback
}

// Cheap "+15% brightness" approximation for the hover state: blend 15%
// toward white rather than computing HSL — good enough for a stroke-only
// line icon, not worth a color-math dependency.
function lighten(hex: string): string {
  const n = parseInt(hex.replace('#', ''), 16)
  const r = Math.min(255, Math.round(((n >> 16) & 255) * 1.15))
  const g = Math.min(255, Math.round(((n >> 8) & 255) * 1.15))
  const b = Math.min(255, Math.round((n & 255) * 1.15))
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`
}

export function SymbolSvg({ width = 64, height = 64, strokeWidth = 2, className, rotation, selected, children, ...rest }:
  PidSymbolProps & { fallback: string; children: ReactNode }) {
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

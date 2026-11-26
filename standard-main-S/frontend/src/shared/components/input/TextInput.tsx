import { forwardRef } from 'react'
import type { InputHTMLAttributes } from 'react'

const BASE_STYLE: React.CSSProperties = {
  background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
  borderRadius: 6, color: 'var(--text-primary)', font: 'inherit',
  fontSize: 13, padding: '9px 12px', outline: 'none',
}

// The plain "9px 12px" text-input style — byte-identical across Sidebar's
// new/rename-project modals and IngestScreen's API-key modal fields.
// `focusAccent` reproduces the onFocus/onBlur border-color toggle used by
// the Sidebar modals but not the Ingest ones — opt-in per call site so
// behavior stays exactly as it was pre-extraction.
export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { focusAccent?: boolean }>(
  ({ style, focusAccent, onFocus, onBlur, ...rest }, ref) => (
    <input
      ref={ref}
      style={{ ...BASE_STYLE, ...style }}
      onFocus={e => { if (focusAccent) e.currentTarget.style.borderColor = 'var(--accent)'; onFocus?.(e) }}
      onBlur={e => { if (focusAccent) e.currentTarget.style.borderColor = 'var(--border)'; onBlur?.(e) }}
      {...rest}
    />
  ),
)

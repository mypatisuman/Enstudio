import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown } from 'lucide-react'

// Custom dropdown so the option list can carry the app's dark theme + hover
// highlight (a native <select>'s menu is drawn by the OS and can't be styled).
// The menu is portaled to document.body (same pattern as the app's modals —
// see ConfirmModal) and positioned by the trigger button's screen coordinates,
// so it always paints above sticky table headers / scroll containers instead
// of being clipped or stacked underneath them. Shared across Validation and
// Review filter bars (and any future filter row) — one dropdown, one look.
export interface SelectOption { value: string; label: string }

export function FilterSelect({ value, options, onChange, style, ariaLabel }: {
  value: string
  options: SelectOption[]
  onChange: (v: string) => void
  style?: React.CSSProperties
  ariaLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const [rect, setRect] = useState<{ left: number; top: number; width: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const current = options.find(o => o.value === value)

  const reposition = useCallback(() => {
    const r = btnRef.current?.getBoundingClientRect()
    if (r) setRect({ left: r.left, top: r.bottom + 4, width: r.width })
  }, [])

  useLayoutEffect(() => { if (open) reposition() }, [open, reposition])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (btnRef.current?.contains(t) || menuRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [open, reposition])

  return (
    <div className="fsel-wrap" style={style}>
      <button
        ref={btnRef}
        type="button" className={`fsel${open ? ' fsel--open' : ''}`}
        onClick={() => setOpen(o => !o)} aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel}
      >
        <span className="fsel-value">{current?.label ?? ''}</span>
        <ChevronDown size={15} className="fsel-chevron" />
      </button>
      {open && rect && createPortal(
        <div
          ref={menuRef} className="fsel-menu" role="listbox"
          style={{ position: 'fixed', left: rect.left, top: rect.top, width: rect.width }}
        >
          {options.map(o => (
            <button
              key={o.value} type="button" role="option" aria-selected={o.value === value}
              className={`fsel-opt${o.value === value ? ' fsel-opt--sel' : ''}`}
              onClick={() => { onChange(o.value); setOpen(false) }}
            >
              {o.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </div>
  )
}

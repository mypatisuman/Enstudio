import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

interface Props {
  title: string
  titleColor?: string
  width?: number
  body: React.ReactNode
  confirmLabel: React.ReactNode
  confirmDisabled?: boolean
  confirmDanger?: boolean
  onConfirm: () => void
  onCancel: () => void
  // A caller nested inside ANOTHER portaled modal (e.g. a delete-confirm
  // opened from within a drill-down modal that's also portaled) may need to
  // render above it. Since this component now portals itself to
  // document.body as a true top-level sibling (see createPortal below), a
  // plain z-index bump is enough — it's compared directly against the other
  // portal's z-index at the same stacking level, no longer trapped inside
  // whatever stacking context the caller happens to be nested in.
  zIndex?: number
}

/** Shared centered overlay modal used for New/Rename/Delete project dialogs.
 * Portals itself to document.body — a caller nested inside another portaled
 * modal previously had this render trapped inside that modal's own stacking
 * context, where no z-index on this component could ever escape it (a
 * child's z-index only competes with siblings in the SAME stacking context).
 * Portaling directly makes it a true top-level sibling of every other modal. */
export default function ConfirmModal({
  title, titleColor = 'var(--text-primary)', width = 380,
  body, confirmLabel, confirmDisabled, confirmDanger, onConfirm, onCancel, zIndex = 9999,
}: Props) {
  const [open, setOpen] = useState(false)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    // enter on the next frame so it animates from the closed state
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])
  // Play the exit, then unmount via the parent. Only the dismiss gesture — a
  // confirm may show a loading label and stay mounted, so leave it untouched.
  const dismiss = () => { setOpen(false); setTimeout(onCancel, 160) }

  // Focus the confirm button so Enter immediately triggers it (native button
  // behavior — no manual keydown handling needed) without the user having to
  // tab/click first. Escape mirrors clicking the backdrop. Tab/Shift+Tab are
  // trapped between just these two buttons — Cancel sits BEFORE Delete in DOM
  // order but Delete is focused first, so plain Tab would otherwise walk out
  // of the modal entirely (nothing after Delete) instead of wrapping to
  // Cancel; without this the two buttons aren't actually cycle-able by Tab.
  useEffect(() => {
    confirmRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { dismiss(); return }
      if (e.key !== 'Tab') return
      e.preventDefault()
      const focusCancel = document.activeElement === confirmRef.current
      ;(focusCancel ? cancelRef.current : confirmRef.current)?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return createPortal(
    <div className={`modal-backdrop${open ? ' open' : ''}`} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex,
    }} onClick={e => { if (e.target === e.currentTarget) dismiss() }}>
      <div className="modal-dialog" style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '24px 24px 20px', width,
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: titleColor }}>
          {title}
        </div>
        {body}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button ref={cancelRef} className="btn btn-ghost" onClick={dismiss}>Cancel</button>
          <button
            ref={confirmRef}
            className="btn btn-primary"
            style={confirmDanger ? { background: 'var(--danger)', color: '#fff', border: 'none' } : undefined}
            disabled={confirmDisabled}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

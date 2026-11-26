import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import type { Project } from '../../../App'

/** Centered modal listing projects to pick from (Open Project / Explore Canvas). */
export function ProjectPickerModal({ title, projects, onPick, onCancel }: {
  title: string
  projects: Project[]
  onPick: (p: Project) => void
  onCancel: () => void
}) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const dismiss = () => { setOpen(false); setTimeout(onCancel, 160) }

  return createPortal(
    <div
      className={`modal-backdrop${open ? ' open' : ''}`}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
      }}
      onClick={e => { if (e.target === e.currentTarget) dismiss() }}
    >
      <div className="modal-dialog" style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '22px 22px 18px', width: 420, maxHeight: '76vh',
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>{title}</div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', maxHeight: '52vh' }}>
          {projects.length === 0 ? (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '18px 0', textAlign: 'center' }}>
              No projects yet — create one first.
            </div>
          ) : projects.map(p => (
            <button key={p.id} className="picker-row" onClick={() => onPick(p)}>
              <span className="picker-row__name">{p.name || p.id}</span>
              <span className="picker-row__meta">{p.instruments} instr · {p.equipment} equip · {p.drawings} dwg</span>
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  )
}

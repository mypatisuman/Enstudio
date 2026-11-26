import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { getProjectStats } from '../../services/project'
import { useCanvasThumbnails } from '../thumbnails/useCanvasThumbnails'
import type { Project } from '../../App'

// Granular relative time (minutes → hours → days). SQLite datetime('now') is
// UTC with no zone marker; normalize to UTC so the minute/hour math is right.
function ago(iso: string): string {
  const norm = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(iso)
    ? iso.replace(' ', 'T') + 'Z'
    : iso
  const d = new Date(norm)
  if (isNaN(d.getTime())) return iso.slice(0, 10)
  const mins = Math.floor((Date.now() - d.getTime()) / 60000)
  if (mins < 1)  return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)  return `${hrs} hour${hrs === 1 ? '' : 's'} ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  return d.toISOString().slice(0, 10)
}

/** Popup listing every project with name, last-extracted time, and quality %. */
export function AllProjectsModal({ projects, onPick, onCancel }: {
  projects: Project[]
  onPick: (p: Project) => void
  onCancel: () => void
}) {
  const [open, setOpen] = useState(false)
  const [pct, setPct] = useState<Record<string, number>>({})
  // Real Canvas-screen thumbnails for every project shown here (not just the
  // top 3 the Recent Projects panel already captures) — queued one at a time.
  const { thumbs, captureNode } = useCanvasThumbnails(projects)

  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])

  useEffect(() => {
    let alive = true
    projects.forEach(async p => {
      try {
        const stats = await getProjectStats(p.id)
        if (!alive) return
        const ratio = stats.node_count > 0 ? stats.edge_count / stats.node_count : 0
        setPct(prev => ({ ...prev, [p.id]: Math.round(Math.min(ratio / 1.2, 1) * 100) }))
      } catch { /* ignore */ }
    })
    return () => { alive = false }
  }, [projects])

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
        borderRadius: 14, padding: '22px 22px 18px', width: 480, maxHeight: '84vh',
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
            All projects <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>({projects.length})</span>
          </div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        <div className="allproj-list">
          {projects.length === 0 ? (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '18px 0', textAlign: 'center' }}>
              No projects yet.
            </div>
          ) : projects.map(p => (
            <button key={p.id} className="allproj-row" onClick={() => onPick(p)}>
              <span className="allproj-row__thumb" aria-hidden="true">
                {thumbs[p.id] ? (
                  <img src={thumbs[p.id]} alt="" />
                ) : (
                  <svg viewBox="0 0 60 44" fill="none" preserveAspectRatio="xMidYMid slice">
                    <rect x="6" y="14" width="16" height="12" rx="2" className="rp-bp" />
                    <circle cx="42" cy="20" r="7" className="rp-bp" />
                    <path d="M22 20 H35" className="rp-bp" />
                    <path d="M42 27 V36 H14 V26" className="rp-bp" />
                    <circle cx="35" cy="20" r="2" className="rp-bp-node" />
                  </svg>
                )}
              </span>
              <div className="allproj-row__body">
                <div className="allproj-row__name">{p.name || p.id}</div>
                <div className="allproj-row__meta">
                  {p.instruments} instr · {p.equipment} equip · {
                    p.last_extraction ? `Extracted ${ago(p.last_extraction)}`
                      : p.last_activity ? `Described ${ago(p.last_activity)}`
                      : (p.status || 'pending')
                  }
                </div>
              </div>
              <span className="allproj-row__pct" title="Extraction quality">{pct[p.id] != null ? `${pct[p.id]}%` : ''}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Off-screen — real Canvas-screen thumbnail capture, one project at a time */}
      {captureNode}
    </div>,
    document.body,
  )
}

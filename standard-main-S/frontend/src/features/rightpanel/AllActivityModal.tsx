import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  X, CheckCircle2, AlertTriangle, Loader2, Type,
  Sparkles, Upload, Network, Shapes, Waypoints, ShieldCheck,
} from 'lucide-react'
import type { LogEntry } from '../../state/extraction/types'

// Icon SHAPE per pipeline stage, color/background per status — see
// RightPanel.tsx's iconFor/iconForStage for the full rationale (real labels
// like "Complete"/"Extracting" never contain substrings like "completed", so
// matching against label text silently never matched anything).
function iconForStage(stage: string) {
  switch (stage) {
    case 'init':         return <Sparkles size={14} />
    case 'hash':          return <Upload size={14} />
    case 'cv_extracting': return <Network size={14} />
    case 'cv_symbols':    return <Shapes size={14} />
    case 'cv_text':       return <Type size={14} />
    case 'cv_lines':      return <Waypoints size={14} />
    case 'llm_verify':    return <ShieldCheck size={14} />
    case 'done':          return <CheckCircle2 size={14} />
    case 'error':
    case 'warn':          return <AlertTriangle size={14} />
    default:               return <Type size={14} />
  }
}
function iconFor(stage: string, status: string) {
  if (status === 'running') return <Loader2 size={14} className="notif-spin" />
  return iconForStage(stage)
}

// Relative time from an epoch-ms timestamp — same format RightPanel's own
// preview list uses (agoMs), so this expanded view reads consistently with it.
function agoMs(ms: number): string {
  const diff = Date.now() - ms
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

/** Popup listing every extraction-log activity entry (not just the last 6). */
export function AllActivityModal({ activity, nameOf, onCancel }: {
  activity: (LogEntry & { pid: string })[]
  nameOf: (pid: string) => string
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
        borderRadius: 14, padding: '22px 22px 18px', width: 480, maxHeight: '84vh',
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
            Activity feed <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>({activity.length})</span>
          </div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        {activity.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '18px 0', textAlign: 'center' }}>
            No activity yet — it fills in as extractions run.
          </div>
        ) : (
          <div className="rp-timeline-card">
            <div className="rp-timeline allact-scroll">
              {activity.map((a, i) => (
                <div className="rp-tl-item" key={i}>
                  <div className={`rp-tl-icon ${a.status}`}>{iconFor(a.stage, a.status)}</div>
                  <div className="rp-tl-body">
                    <div className="rp-tl-label">{a.label}</div>
                    <div className="rp-tl-detail">{nameOf(a.pid)} · {a.detail}</div>
                  </div>
                  <div className="rp-tl-time">{agoMs(a.startedAt)}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

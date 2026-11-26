import { useState, useEffect, useContext } from 'react'
import { listen } from '@tauri-apps/api/event'
import {
  CheckCircle2, AlertTriangle, Loader2, Type,
  Sparkles, Upload, Network, Shapes, Waypoints, ShieldCheck,
} from 'lucide-react'
import { Ctx } from '../../state/useExtraction'
import { listProjects, getProjectStats } from '../../services/project'
import { storedUserId } from '../../services/authApi'
import { AllProjectsModal } from './AllProjectsModal'
import { AllActivityModal } from './AllActivityModal'
import { useCanvasThumbnails } from '../thumbnails/useCanvasThumbnails'
import type { Project } from '../../App'
import type { LogEntry } from '../../state/extraction/types'

// Verified against real persisted timestamps (see conversation): the backend
// flips "Extracting: running" and "Symbols: running" at the SAME instant, then
// Text/Lines only start once Symbols itself finishes. Confirmed desired order:
// Lines, Text, Symbols, Extracting (Extracting LAST/bottom of the group, tied
// with Symbols broken in Symbols's favor) — Complete/Verifying/Lines/Text/
// Symbols all still ordered by real time; only the Extracting-vs-Symbols tie
// is pinned so it doesn't depend on incidental array/load order.
const stageTier = (stage: string) => (stage === 'cv_extracting' ? 1 : 0)
const byTime = (a: LogEntry, b: LogEntry) => {
  const inSameDetectorGroup = ['cv_extracting', 'cv_symbols', 'cv_text', 'cv_lines'].includes(a.stage)
    && ['cv_extracting', 'cv_symbols', 'cv_text', 'cv_lines'].includes(b.stage)
  if (inSameDetectorGroup) {
    const t = stageTier(a.stage) - stageTier(b.stage)   // Extracting (1) sorts after its children (0)
    if (t !== 0) return t
  }
  return b.startedAt - a.startedAt
}
const latestAt = (log: LogEntry[]) => log.reduce((m, e) => Math.max(m, e.startedAt), 0)

// Epoch-ms from a last_extraction string. SQLite datetime('now') is UTC with no
// zone marker, so normalize to UTC before parsing (else it's read as local).
const tsMs = (iso: string): number => {
  const norm = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(iso) ? iso.replace(' ', 'T') + 'Z' : iso
  const t = Date.parse(norm)
  return isNaN(t) ? 0 : t
}

// Icon SHAPE per pipeline STAGE (so "Extracting", "Symbols", "Verifying",
// "Complete" etc. each read distinctly, not all sharing one checkmark) while
// still in progress overrides to a spinner regardless of stage. Box color/
// background is separately driven by STATUS via the CSS classes below (a
// prior version tried to pick the icon from label substrings like
// "completed"/"uploaded", but real labels are "Complete"/"Extracting" etc.,
// which never contain those substrings — every entry silently got the same
// generic icon no matter what actually happened).
function iconForStage(stage: string) {
  switch (stage) {
    case 'init':         return <Sparkles size={14} />
    case 'hash':          return <Upload size={14} />        // "File ready"
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

// Relative time from an ISO-ish timestamp string. Granular: minutes → hours →
// days. SQLite datetime('now') yields "YYYY-MM-DD HH:MM:SS" in UTC with no zone
// marker, which JS would otherwise misparse as local time and throw the
// minute/hour math off by the timezone offset — so normalize it to UTC first.
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

// Relative time from an epoch-ms timestamp (log entries use Date.now()).
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

export function RightPanel({ activeProject, setActiveProject }: {
  activeProject: Project | null
  setActiveProject: (p: Project | null) => void
}) {
  const ctx = useContext(Ctx)
  const byProject = ctx?.byProject ?? {}
  const [projects, setProjects] = useState<Project[]>([])
  const [showAll, setShowAll] = useState(false)
  const [showActivity, setShowActivity] = useState(false)
  // Real per-project extraction-quality % (edge/node ratio → same scale as HomeScreen).
  const [pct, setPct] = useState<Record<string, number>>({})

  useEffect(() => {
    let alive = true
    const load = () => listProjects(storedUserId()).then(r => { if (alive) setProjects(r) }).catch(() => {})
    load()
    const un = listen('project-updated', load)
    return () => { alive = false; un.then(f => f()) }
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

  const nameOf = (pid: string) => projects.find(p => p.id === pid)?.name || pid

  // Most-recently-active first — projects.last_activity, written on any real
  // content change (extraction OR Describe adds/edits), so a project built
  // entirely through Describe (never extracted) still surfaces here instead
  // of permanently sorting last. Falls back to last_extraction for rows from
  // before last_activity existed.
  const tsOf = (p: Project) => {
    const iso = p.last_activity || p.last_extraction
    const t = iso ? new Date(iso).getTime() : NaN
    return isNaN(t) ? -Infinity : t
  }
  const sortedProjects = [...projects].sort((a, b) => tsOf(b) - tsOf(a))

  // Real Canvas-screen thumbnails for the 3 cards shown here — see useCanvasThumbnails.
  const topThree = sortedProjects.slice(0, 3)
  const { thumbs, captureNode } = useCanvasThumbnails(topThree)

  // Activity feed, per project, newest-active project first. Sourced ENTIRELY
  // from byProject[pid].log, which ExtractionContext seeds from the DB's
  // activity_log table on mount — real rows only. No client-side synthesis:
  // if the DB has no row for a project, nothing shows for it here.
  // Ordered by real time (see byTime above) — most recently started first.
  const activityFor = (pid: string): (LogEntry & { pid: string })[] =>
    [...(byProject[pid]?.log ?? [])]
      .sort(byTime)
      .map(e => ({ pid, ...e }))

  const recencyOf = (pid: string): number => {
    const p = projects.find(pr => pr.id === pid)
    const lastTouched = p?.last_activity || p?.last_extraction
    return Math.max(latestAt(byProject[pid]?.log ?? []), lastTouched ? tsMs(lastTouched) : 0)
  }

  const allActivity = [...new Set([...Object.keys(byProject), ...projects.map(p => p.id)])]
    .sort((a, b) => recencyOf(b) - recencyOf(a))
    .flatMap(activityFor)
  const activity = allActivity.slice(0, 6)

  return (
    <>
    <div className="home-dock-grid">

        {/* Recent projects — one card, each project a flat divided row */}
        <section className="rp-section">
          <div className="rp-sec-head">
            <div className="rp-heading">Recent Projects</div>
            <button className="home-sec-link" style={{ fontSize: '11px' }} onClick={() => setShowAll(true)}>View all</button>
          </div>
          {projects.length === 0 ? (
            <div className="rp-empty">No projects yet</div>
          ) : (
            <div className="rp-timeline-card">
            <div className="rp-proj-list">
              {sortedProjects.slice(0, 3).map(p => (
                <button
                  key={p.id}
                  className={`rp-proj${activeProject?.id === p.id ? ' active' : ''}`}
                  onClick={() => setActiveProject(activeProject?.id === p.id ? null : p)}
                >
                  <span className="rp-proj__thumb" aria-hidden="true">
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
                    {byProject[p.id]?.isExtracting && <span className="rp-proj__busy" />}
                  </span>
                  <span className="rp-proj__body">
                    <span className="rp-proj__name">{p.name || p.id}</span>
                    <span className="rp-proj__meta">
                      {p.instruments} instr · {p.equipment} equip
                      <br />{
                        p.last_extraction ? `Extracted ${ago(p.last_extraction)}`
                          : p.last_activity ? `Described ${ago(p.last_activity)}`
                          : (p.status || 'pending')
                      }
                    </span>
                  </span>
                  <span className="rp-proj__pct" title="Extraction quality">{pct[p.id] != null ? `${pct[p.id]}%` : ''}</span>
                </button>
              ))}
            </div>
            </div>
          )}
        </section>

        {/* Activity feed — one card, header above (matches Recent projects) */}
        <section className="rp-section">
          <div className="rp-sec-head">
            <div className="rp-heading">Latest Activity</div>
            <button className="home-sec-link" style={{ fontSize: '11px' }} onClick={() => setShowActivity(true)}>View all</button>
          </div>
          {activity.length === 0 ? (
            <div className="rp-empty">No recent activity</div>
          ) : (
            <div className="rp-timeline-card">
              <div className="rp-timeline">
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
        </section>

      </div>

      {showActivity && (
        <AllActivityModal
          activity={allActivity}
          nameOf={nameOf}
          onCancel={() => setShowActivity(false)}
        />
      )}

      {showAll && (
        <AllProjectsModal
          projects={sortedProjects}
          onPick={p => { setActiveProject(p); setShowAll(false) }}
          onCancel={() => setShowAll(false)}
        />
      )}

      {/* Off-screen — real Canvas-screen thumbnail capture, one project at a time */}
      {captureNode}
    </>
  )
}

import { useState, useEffect, useMemo, useCallback } from 'react'
import { AlertOctagon, AlertTriangle, Info, RefreshCw, CheckCircle2 } from 'lucide-react'
import type { Project, Screen } from '../../App'
import { requestCanvasFocus } from '../../features/canvas/focusBus'
import { ErrorBanner } from '../../shared/components/error/ErrorBanner'
import { NoProjectState } from '../../shared/components/empty/NoProjectState'
import { StatCard } from '../../shared/components/card/StatCard'
import { RULES } from '../../features/validation/rules'
import { FilterSelect } from '../../shared/components/select/FilterSelect'
import { validationScore } from '../../features/validation/engine'
import { runAndCacheValidation } from '../../features/validation/run'
import { getCached, subscribeValidation } from '../../features/validation/cache'
import { loadStatuses, saveStatuses, type StatusMap } from '../../features/validation/status'
import type { ValidationIssue, ValidationContext, Severity, IssueStatus } from '../../features/validation/types'

interface Props { project: Project | null; setActiveScreen?: (s: Screen) => void }

const SEV_META: Record<Severity, { label: string; color: string; Icon: typeof AlertTriangle }> = {
  critical: { label: 'Critical', color: '#ef4444', Icon: AlertOctagon },
  warning:  { label: 'Warning',  color: '#eab308', Icon: AlertTriangle },
  info:     { label: 'Info',     color: '#3b82f6', Icon: Info },
}

// Relative time from epoch-ms — same shape as the activity feed's own agoMs.
function relTime(ms: number): string {
  const mins = Math.floor((Date.now() - ms) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

const selectStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6,
  color: 'var(--text-primary)', font: 'inherit', fontSize: 12.5, padding: '7px 10px', outline: 'none', cursor: 'pointer',
}

export default function ValidationScreen({ project, setActiveScreen }: Props) {
  const [ctx,     setCtx]     = useState<ValidationContext | null>(null)
  const [issues,  setIssues]  = useState<ValidationIssue[]>([])
  const [ranAt,   setRanAt]   = useState<number | null>(null)
  const [status,  setStatus]  = useState<StatusMap>({})
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  const [sev,    setSev]    = useState<'all' | Severity>('all')
  const [rule,   setRule]   = useState<'all' | string>('all')
  const [stat,   setStat]   = useState<'all' | IssueStatus>('all')
  const [search, setSearch] = useState('')

  const applyResult = useCallback((r: { issues: ValidationIssue[]; ctx: ValidationContext; ranAt: number }) => {
    setCtx(r.ctx); setIssues(r.issues); setRanAt(r.ranAt)
  }, [])

  // Manual refresh — re-run through the shared runner (which also updates the
  // cache) so a manual and an automatic run stay consistent. Never on render.
  const runFor = useCallback(async (pid: string) => {
    setLoading(true); setError('')
    try {
      applyResult(await runAndCacheValidation(pid))
    } catch (e: unknown) {
      setError(typeof e === 'string' ? e : JSON.stringify(e))
    } finally {
      setLoading(false)
    }
  }, [applyResult])

  // On project open: prefer the cached result (pre-warmed after extraction, so
  // this is instant) and only compute if nothing is cached yet. Keyed on
  // project id, not the object — same rationale as every other screen.
  useEffect(() => {
    if (!project) { setCtx(null); setIssues([]); setRanAt(null); return }
    setStatus(loadStatuses(project.id))
    setSev('all'); setRule('all'); setStat('all'); setSearch('')
    const cached = getCached(project.id)
    if (cached) { applyResult(cached); setLoading(false) }
    else runFor(project.id)
  }, [project?.id, runFor, applyResult])

  // Live-update when auto-validation caches a fresh run for this project (e.g.
  // an extraction finished while this screen was open or in the background).
  useEffect(() => {
    if (!project) return
    return subscribeValidation(pid => {
      if (pid !== project.id) return
      const c = getCached(pid)
      if (c) applyResult(c)
    })
  }, [project?.id, applyResult])

  const statusOf = useCallback((id: string): IssueStatus => status[id] ?? 'open', [status])

  const setIssueStatus = useCallback((id: string, next: IssueStatus) => {
    if (!project) return
    setStatus(prev => {
      const updated = { ...prev, [id]: next }
      saveStatuses(project.id, updated)
      return updated
    })
  }, [project])

  const jump = useCallback((tag?: string) => {
    if (!tag) return
    requestCanvasFocus(tag)
    setActiveScreen?.('canvas')
  }, [setActiveScreen])

  // Counts for the dashboard — by severity among OPEN issues, plus resolved.
  const counts = useMemo(() => {
    const c = { critical: 0, warning: 0, info: 0, resolved: 0, ignored: 0 }
    for (const i of issues) {
      const s = statusOf(i.id)
      if (s === 'resolved') { c.resolved++; continue }
      if (s === 'ignored')  { c.ignored++;  continue }
      c[i.severity]++
    }
    return c
  }, [issues, statusOf])

  const score = useMemo(() => {
    if (!ctx) return 100
    const open = issues.filter(i => statusOf(i.id) === 'open')
    return validationScore(open, ctx)
  }, [issues, ctx, statusOf])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return issues.filter(i => {
      if (sev !== 'all'  && i.severity !== sev)  return false
      if (rule !== 'all' && i.ruleId !== rule)   return false
      if (stat !== 'all' && statusOf(i.id) !== stat) return false
      if (q) {
        const hay = `${i.title} ${i.description} ${i.tag ?? ''} ${i.drawing ?? ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [issues, sev, rule, stat, search, statusOf])

  if (!project) {
    return <NoProjectState icon="✓" title="No project selected" body="Pick a project from the sidebar to validate." />
  }

  return (
    <>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="section-heading" style={{ margin: 0 }}>Validation — {project.name}</span>
        {ranAt && !loading && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Auto-checked {relTime(ranAt)}
          </span>
        )}
        <button
          className="btn btn-ghost tip" data-tip="Re-run validation"
          onClick={() => runFor(project.id)} disabled={loading}
          style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <RefreshCw size={15} className={loading ? 'val-spin' : undefined} /> {loading ? 'Checking…' : 'Refresh'}
        </button>
      </div>

      {error && <ErrorBanner message={error} />}

      {/* Dashboard */}
      <div className="stat-row">
        <StatCard label="Critical"     value={counts.critical} valueClass={counts.critical ? 'danger'  : undefined} sub="must fix" />
        <StatCard label="Warnings"     value={counts.warning}  valueClass={counts.warning  ? 'warning' : undefined} sub="review recommended" />
        <StatCard label="Information"  value={counts.info}     sub="advisory" />
        <StatCard label="Resolved"     value={counts.resolved} valueClass={counts.resolved ? 'success' : undefined} sub={`${counts.ignored} ignored`} />
        <StatCard
          label="Validation Score" value={`${score}%`}
          valueClass={score >= 90 ? 'success' : score >= 70 ? 'warning' : 'danger'}
          sub={`${issues.length} issue${issues.length === 1 ? '' : 's'} found`}
        />
      </div>

      {/* Score bar */}
      <div className="rv-progress" style={{ marginTop: 12 }} title={`Validation score ${score}%`}>
        <div
          className="rv-progress__seg"
          style={{ width: `${score}%`, background: score >= 90 ? 'var(--success)' : score >= 70 ? '#eab308' : 'var(--danger)' }}
        />
      </div>

      {/* Filters — search on its own row; the three selects share one line */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '16px 0 14px' }}>
        <input
          type="text" placeholder="Search issues, tags, drawings…"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{
            width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 6, color: 'var(--text-primary)', font: 'inherit', fontSize: 13, padding: '7px 12px', outline: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'nowrap' }}>
        <FilterSelect
          style={{ flex: 1, minWidth: 0 }}
          value={sev} onChange={v => setSev(v as typeof sev)}
          options={[
            { value: 'all', label: 'All severities' },
            { value: 'critical', label: 'Critical' },
            { value: 'warning', label: 'Warning' },
            { value: 'info', label: 'Info' },
          ]}
        />
        <FilterSelect
          style={{ flex: 1, minWidth: 0 }}
          value={rule} onChange={setRule}
          options={[{ value: 'all', label: 'All types' }, ...RULES.map(r => ({ value: r.id, label: r.label }))]}
        />
        <FilterSelect
          style={{ flex: 1, minWidth: 0 }}
          value={stat} onChange={v => setStat(v as typeof stat)}
          options={[
            { value: 'all', label: 'All statuses' },
            { value: 'open', label: 'Open' },
            { value: 'ignored', label: 'Ignored' },
            { value: 'resolved', label: 'Resolved' },
          ]}
        />
        </div>
      </div>

      {/* Issues */}
      {loading ? (
        <div className="rv-empty">Running validation…</div>
      ) : filtered.length === 0 ? (
        <div className="rv-empty">
          {issues.length === 0
            ? <> <CheckCircle2 size={18} style={{ color: 'var(--success)', verticalAlign: -3, marginRight: 6 }} /> No validation issues — the diagram passed all checks.</>
            : 'No issues match the current filters.'}
        </div>
      ) : (
        <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 90 }}>Severity</th>
              <th>Issue</th>
              <th style={{ width: 130 }}>Tag</th>
              <th style={{ width: 90 }}>Drawing</th>
              <th style={{ width: 130 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(issue => {
              const { color, Icon, label } = SEV_META[issue.severity]
              const st = statusOf(issue.id)
              return (
                <tr key={issue.id} style={st === 'resolved' ? { opacity: 0.55 } : undefined}>
                  <td>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color }}>
                      <Icon size={15} /> <span style={{ fontSize: 12 }}>{label}</span>
                    </span>
                  </td>
                  <td>
                    <div style={{ fontWeight: 600, marginBottom: 2 }}>{issue.title}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{issue.description}</div>
                    {issue.suggestion && (
                      <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 3 }}>💡 {issue.suggestion}</div>
                    )}
                  </td>
                  <td>
                    {issue.tag
                      ? <button className="rv-tag-link" onClick={() => jump(issue.tag)} title="Jump to Canvas">
                          {issue.tag}
                        </button>
                      : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                  </td>
                  <td style={{ fontSize: 12 }}>{issue.drawing || '—'}</td>
                  <td>
                    <select
                      style={{ ...selectStyle, padding: '5px 8px', width: '100%' }}
                      value={st} onChange={e => setIssueStatus(issue.id, e.target.value as IssueStatus)}
                    >
                      <option value="open">Open</option>
                      <option value="ignored">Ignored</option>
                      <option value="resolved">Resolved</option>
                    </select>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        </div>
      )}
    </>
  )
}

import type { EntryStatus, LogEntry } from './types'

export function mergeEntry(prev: LogEntry[], next: LogEntry): LogEntry[] {
  const idx = prev.findIndex(e => e.stage === next.stage)
  if (idx === -1) return [...prev, next]
  const existing = prev[idx]
  const updated = [...prev]
  // Prefer a backend-measured duration when present (accurate for the parallel
  // Text/Lines detectors); otherwise fall back to wall-clock since the entry
  // first appeared when a running entry transitions to complete/error.
  const durationMs = next.durationMs
    ?? (existing.status === 'running' && next.status !== 'running'
      ? Date.now() - existing.startedAt
      : existing.durationMs)
  updated[idx] = { ...next, startedAt: existing.startedAt, durationMs }
  return updated
}

export function parseEntry(p: Record<string, unknown>): LogEntry | null {
  const stage  = String(p.stage  ?? '')
  const status = String(p.status ?? '')
  if (stage === 'finished') return null  // terminal signal — no UI row

  const n = (k: string) => Number(p[k] ?? 0)
  const s = (k: string) => String(p[k]  ?? '')

  let label:  string
  let detail: string
  const entryStage = stage
  let es: EntryStatus = status === 'running' ? 'running' : 'complete'
  let durationMs: number | undefined   // backend-measured time, when provided
  let indent = false                   // detector rows nest under the Extracting parent
  const now = Date.now()

  switch (stage) {

    // ── Startup ────────────────────────────────────────────────────────────
    case 'init':
      label  = 'Initialising'
      detail = s('file')
      es     = 'info'
      break

    case 'pdf_render':
      label  = 'Rendering PDF'
      detail = status === 'running'
        ? 'converting page 1 to image…'
        : `ready · ${Math.round(n('bytes') / 1024)} KB`
      break

    case 'hash':
      label  = 'File ready'
      detail = s('filename')
      es     = 'info'
      break

    case 'cache':
      label  = 'Cache hit'
      detail = s('message') || 'already processed — loading from cache'
      es     = 'info'
      break

    // ── CV detection — a parent "Extracting" row with the three detectors
    //    (Symbols, Lines, Text) nested underneath, each with its own time ────
    case 'cv_extracting': {
      label = 'Extracting'
      if (status === 'running') {
        detail = ''
        es     = 'running'
      } else {
        detail = ''
        es     = 'complete'
        if (p.elapsed_s != null) durationMs = n('elapsed_s') * 1000   // total time
      }
      break
    }

    case 'cv_symbols':
      label  = 'Symbols'
      indent = true
      if (status === 'running') {
        detail = 'detecting…'
        es     = 'running'
      } else {
        detail = `${n('symbol_count')} detected`
        if (p.sym_error) { detail += ` · ${s('sym_error')}`; es = 'warn' }
        if (p.elapsed_s != null) durationMs = n('elapsed_s') * 1000
      }
      break

    case 'cv_text':
      label  = 'Text'
      indent = true
      if (status === 'running') {
        detail = 'reading…'
        es     = 'running'
      } else {
        detail = `${n('text_count')} labels`
        if (p.text_error) { detail += ` · ${s('text_error')}`; es = 'warn' }
        if (p.elapsed_s != null) durationMs = n('elapsed_s') * 1000
      }
      break

    case 'cv_lines':
      label  = 'Lines'
      indent = true
      if (status === 'running') {
        detail = 'detecting…'
        es     = 'running'
      } else {
        detail = `${n('line_count')} lines`
        if (p.line_error) { detail += ` · ${s('line_error')}`; es = 'warn' }
        if (p.elapsed_s != null) durationMs = n('elapsed_s') * 1000
      }
      break

    // ── LLM verification ───────────────────────────────────────────────────
    case 'llm_verify':
      label = 'Verifying'
      if (status === 'running') {
        detail = ''
        es     = 'running'
      } else {
        detail = `${n('nodes')} nodes · ${n('instruments')} instruments · ${n('equipment')} equipment · ${n('connections')} connections`
        es     = 'complete'
      }
      break

    // ── Merge + done ───────────────────────────────────────────────────────
    case 'merge':
      return null   // "Saving to project" — hidden from the progress log

    case 'cv_summary':
      return null   // internal CV summary build — hidden from the progress log

    case 'edge_paths':
      return null   // pipe-path geometry sidecar — internal, hidden from the log

    case 'done':
      label  = 'Complete'
      detail = `${n('total_nodes')} nodes · ${n('total_instruments')} instruments · `
             + `${n('total_equipment')} equipment · ${n('total_connections')} connections`
             + (p.cached ? ' (cached)' : '')
      es     = 'complete'
      break

    case 'error':
      label  = 'Error'
      detail = s('message')
      es     = 'error'
      break

    case 'warn':
      label  = 'Warning'
      detail = s('message')
      es     = 'warn'
      break

    case 'debug':
      return null  // internal diagnostics — never shown in UI

    case 'log':
      return null  // internal logs — not shown in UI

    default:
      label  = stage || 'Info'
      detail = s('message') || ''
      es     = 'info'
  }

  return { stage: entryStage, label, detail, status: es, startedAt: now, durationMs, indent }
}

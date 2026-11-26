import React, { useState, useCallback, useEffect } from 'react'
import { listen } from '@tauri-apps/api/event'
import { emit } from '@tauri-apps/api/event'
import { listProjects } from '../services/project'
import { runExtraction, cancelExtraction } from '../services/extraction'
import { getActivityLog, saveActivityEntry, clearActivityLog } from '../services/invoke/activity'
import { emptyState } from './extraction/types'
import type { PerProjectState, LogEntry } from './extraction/types'
import { mergeEntry, parseEntry } from './extraction/parseEntry'
import { Ctx } from './useExtraction'

// Persist the activity feed to the DB (activity_log table, 30-day retention —
// see commands/activity.rs) instead of keeping it in memory only. Without
// this, byProject reset to {} on every launch and the feed showed "No recent
// activity" until a fresh extraction ran, even for projects extracted minutes
// earlier in a previous session. DB-backed (not localStorage) so the same
// EngineeringHub shows the same feed regardless of which machine opens it.

// Fire-and-forget persistence — the feed is a convenience view; a failed
// write shouldn't block or error the UI, the in-memory state stays authoritative
// for the running session either way.
function persistEntry(pid: string, entry: LogEntry) {
  saveActivityEntry(pid, entry).catch(() => { /* best-effort */ })
}

export function ExtractionProvider({ children }: { children: React.ReactNode }) {
  const [byProject, setByProject] = useState<Record<string, PerProjectState>>({})

  // Load persisted activity once on mount and seed byProject with it. Nothing
  // is actually running right after a launch, so live flags are cleared and
  // any dangling "running" rows are dropped — a restored feed should show only
  // settled steps, never a stuck spinner or a false "Extracting…" notification.
  useEffect(() => {
    let alive = true
    getActivityLog().then(rows => {
      if (!alive) return
      const grouped: Record<string, PerProjectState> = {}
      for (const { pid, ...entry } of rows) {
        if (entry.status === 'running') continue
        const s = grouped[pid] ?? emptyState()
        grouped[pid] = { ...s, log: [...s.log, entry] }
      }
      setByProject(prev => ({ ...grouped, ...prev }))
    }).catch(() => { /* DB not ready yet — feed just starts empty */ })
    return () => { alive = false }
  }, [])

  // Apply an updater to one project's slice, creating it from emptyState() if absent.
  const updateProject = useCallback(
    (pid: string, updater: (s: PerProjectState) => PerProjectState) => {
      setByProject(prev => ({ ...prev, [pid]: updater(prev[pid] ?? emptyState()) }))
    },
    [],
  )

  // Single mount-once event listener, shared across all concurrently-running
  // projects — every payload now carries project_id (set by the Rust side),
  // so each event is routed to the correct project's slice.
  useEffect(() => {
    const unlisten = listen<Record<string, unknown>>('extraction-progress', ({ payload: p }) => {
      const pid = String(p.project_id ?? '')
      if (!pid) return   // shouldn't happen — Rust always injects project_id

      const entry = parseEntry(p)
      const isFinished = String(p.stage ?? '') === 'finished'

      updateProject(pid, s => {
        const next = { ...s }

        if (entry) {
          next.log = mergeEntry(next.log, entry)
          // Persist the MERGED entry, not the raw one — mergeEntry() freezes
          // startedAt to when this stage first appeared (matches the in-memory
          // ordering the feed sorts by), while the raw `entry` carries a fresh
          // Date.now() from this specific event. Saving the raw one meant every
          // update to a stage (e.g. Extracting: running → complete) overwrote
          // the DB's started_at with the LATEST event's time, so a restarted
          // app would reload a different order than what was showing live.
          const merged = next.log.find(e => e.stage === entry.stage)
          if (merged) persistEntry(pid, merged)
        }

        if (entry?.stage === 'done') {
          next.doneFired   = true
          next.extractDone = true

          const nn   = Number(p.total_nodes       ?? p.nodes       ?? 0)
          const ni   = Number(p.total_instruments ?? p.instruments ?? 0)
          const neq  = Number(p.total_equipment   ?? p.equipment   ?? 0)
          const nc   = Number(p.total_connections ?? p.connections ?? 0)
          const cached = p.cached ? ' (cached)' : ''

          if (next.extractRow !== null) {
            next.rowResult = {
              ...next.rowResult,
              [next.extractRow]: `✓ ${nn} nodes · ${ni} instruments · ${neq} equipment · ${nc} connections${cached}`,
            }
          }
        }

        if (entry?.stage === 'error') {
          next.errorFired   = true
          next.extractError = true
        }

        if (isFinished) {
          const crashed = !next.doneFired && !next.errorFired
          if (crashed) {
            const errMsg = p.stderr ? String(p.stderr) : 'The extraction process crashed unexpectedly.'
            const errEntry: LogEntry = { stage: 'error', label: 'Process Error', detail: errMsg, status: 'error', startedAt: Date.now() }
            next.log = mergeEntry(next.log, errEntry)
            next.extractError = true
            persistEntry(pid, errEntry)
          }
          // Resolve any dangling "running" rows — the process exited without emitting
          // their terminal event (e.g. stdout pipe broke after an API failure).
          // Persist the resolved versions too, so the saved log doesn't leave a
          // "running" row stuck across a restart.
          next.log = next.log.map(e => {
            if (e.status !== 'running') return e
            const resolved: LogEntry = { ...e, status: crashed ? 'error' : 'complete',
              detail: e.detail === 'extracting…' && crashed ? 'failed' : e.detail }
            persistEntry(pid, resolved)
            return resolved
          })
          next.isExtracting = false
        }

        return next
      })

      if (isFinished) {
        listProjects(undefined).catch(() => {})
        emit('project-updated')
      }
    })
    return () => { unlisten.then(f => f()) }
  }, [updateProject])

  const start = useCallback(async (pid: string, sourceId: number, llmOnly?: boolean) => {
    clearActivityLog(pid).catch(() => { /* best-effort */ })
    updateProject(pid, () => ({
      ...emptyState(),
      isExtracting: true,
      extractRow:   sourceId,
    }))
    try {
      await runExtraction(pid, sourceId, llmOnly)
    } catch (err) {
      const msg = String(err)
      if (msg.includes('already running')) {
        // Stale Rust state from a previous crashed run — clear it and retry once
        try { await cancelExtraction(pid) } catch { /* ignore */ }
        try {
          await runExtraction(pid, sourceId, llmOnly)
        } catch (retryErr) {
          const errEntry: LogEntry = { stage: 'error', label: 'Failed to start', detail: String(retryErr), status: 'error', startedAt: Date.now() }
          updateProject(pid, s => ({ ...s, isExtracting: false, extractError: true, log: [errEntry] }))
          persistEntry(pid, errEntry)
        }
      } else {
        const errEntry: LogEntry = { stage: 'error', label: 'Failed to start', detail: msg, status: 'error', startedAt: Date.now() }
        updateProject(pid, s => ({ ...s, isExtracting: false, extractError: true, log: [errEntry] }))
        persistEntry(pid, errEntry)
      }
    }
  }, [updateProject])

  const cancel = useCallback(async (pid: string) => {
    try { await cancelExtraction(pid) } catch { /* ignore */ }
    updateProject(pid, s => ({ ...s, isExtracting: false }))
  }, [updateProject])

  const reset = useCallback((pid: string) => {
    updateProject(pid, () => emptyState())
    clearActivityLog(pid).catch(() => { /* best-effort */ })
  }, [updateProject])

  // For activity that doesn't come from the extraction-progress event stream
  // (e.g. a Describe chat turn) — same persist+merge treatment the event
  // listener above gives extraction's own entries, so it shows up live in
  // the Latest Activity feed instead of only after a reload.
  const logActivity = useCallback((pid: string, entry: LogEntry) => {
    updateProject(pid, s => ({ ...s, log: mergeEntry(s.log, entry) }))
    persistEntry(pid, entry)
  }, [updateProject])

  return (
    <Ctx.Provider value={{ byProject, start, cancel, reset, logActivity }}>
      {children}
    </Ctx.Provider>
  )
}

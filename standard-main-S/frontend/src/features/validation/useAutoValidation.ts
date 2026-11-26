import { useEffect } from 'react'
import { listen } from '@tauri-apps/api/event'
import { runAndCacheValidation } from './run'

// Makes validation part of the pipeline: Extraction → Validation → Review →
// Canvas. When an extraction finishes ('done' — emitted after the DB import,
// with final totals), run validation once in the background and cache it, so
// the Validation screen is instant and current the moment the user gets there.
// Mounted once at the app root; the same listener serves every project.
export function useAutoValidation() {
  useEffect(() => {
    const un = listen<Record<string, unknown>>('extraction-progress', ({ payload: p }) => {
      const pid = String(p.project_id ?? '')
      if (pid && String(p.stage ?? '') === 'done') {
        // Best-effort pre-warm — a failure just means the screen computes on open.
        runAndCacheValidation(pid).catch(() => { /* ignore */ })
      }
    })
    return () => { un.then(f => f()) }
  }, [])
}

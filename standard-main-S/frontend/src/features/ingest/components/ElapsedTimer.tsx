import { useState, useEffect } from 'react'
import type { EntryStatus } from './EntryIcon'

export function ElapsedTimer({ startedAt, durationMs, status }: {
  startedAt: number
  durationMs?: number
  status: EntryStatus
}) {
  // Elapsed ms computed at interval-fire time (not read impurely during
  // render) — same displayed cadence/precision as before, just sourced from
  // state instead of a bare Date.now() call in the render body.
  const [elapsedMs, setElapsedMs] = useState(() => Date.now() - startedAt)

  useEffect(() => {
    if (status !== 'running') return
    const id = setInterval(() => setElapsedMs(Date.now() - startedAt), 100)
    return () => clearInterval(id)
  }, [status, startedAt])

  // Completed entry — show fixed duration
  if (status !== 'running') {
    if (!durationMs) return null
    const secs = (durationMs / 1000).toFixed(1)
    return (
      <span style={{ color: 'var(--text-muted)', fontSize: 11, flexShrink: 0, marginLeft: 'auto', paddingLeft: 8 }}>
        {secs}s
      </span>
    )
  }

  // Running entry — show live ticking elapsed time
  const elapsed = (elapsedMs / 1000).toFixed(1)
  return (
    <span style={{ color: 'var(--accent)', fontSize: 11, flexShrink: 0, marginLeft: 'auto', paddingLeft: 8 }}>
      {elapsed}s
    </span>
  )
}

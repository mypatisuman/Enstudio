import { Spinner } from '../../../shared/components/spinner/Spinner'

export type EntryStatus = 'running' | 'complete' | 'error' | 'warn' | 'info'

export function EntryIcon({ status }: { status: EntryStatus }) {
  if (status === 'running') return <Spinner />
  if (status === 'complete') return <span style={{ color: 'var(--success)', fontSize: 14 }}>✓</span>
  if (status === 'error')    return <span style={{ color: 'var(--danger)',  fontSize: 14 }}>✗</span>
  if (status === 'warn')     return <span style={{ color: 'var(--warning)', fontSize: 13 }}>⚠</span>
  return <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>•</span>
}

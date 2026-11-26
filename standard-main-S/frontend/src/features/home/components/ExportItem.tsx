import { CheckCircle, Clock } from 'lucide-react'

export function ExportItem({ label, exists }: { label: string; exists: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: 'var(--text-secondary)' }}>
      {exists
        ? <CheckCircle size={13} color="var(--success)" strokeWidth={2.5} />
        : <Clock size={13} color="var(--text-muted)" strokeWidth={1.8} />
      }
      <span style={{ color: exists ? 'var(--text-primary)' : 'var(--text-muted)' }}>{label}</span>
    </div>
  )
}

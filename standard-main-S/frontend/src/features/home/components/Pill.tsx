export function Pill({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 9px', borderRadius: 999, fontSize: 11,
      background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
      color: color ?? 'var(--text-secondary)', fontWeight: 600,
    }}>
      <span style={{ fontWeight: 700, color: color ?? 'var(--text-primary)' }}>{value}</span>
      {label}
    </span>
  )
}

export function ProgressBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div style={{ height: 5, borderRadius: 3, background: 'var(--bg-tertiary)', overflow: 'hidden' }}>
      <div style={{ width: `${Math.min(pct, 100)}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.4s ease' }} />
    </div>
  )
}

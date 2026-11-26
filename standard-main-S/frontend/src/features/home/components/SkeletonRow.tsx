export function SkeletonRow() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'flex', gap: 12 }}>
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="skeleton" style={{ flex: 1, height: 80, borderRadius: 8 }} />
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="skeleton" style={{ height: 140, borderRadius: 10, gridColumn: i === 5 ? '1 / -1' : undefined }} />
        ))}
      </div>
    </div>
  )
}

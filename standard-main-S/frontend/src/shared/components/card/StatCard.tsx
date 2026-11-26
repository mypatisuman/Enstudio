import type { ReactNode } from 'react'

// Small bordered KPI tile (.stat-card / .stat-label / .stat-value / .stat-sub) —
// promoted from a HomeScreen-local component since ReviewScreen duplicated
// the exact same CSS-class markup. GapsScreen's "stat-card" tabs are NOT
// this component — those are clickable filter tabs with an icon in the
// label and active-state styling, a genuinely different, interactive shape.
export function StatCard({ label, value, sub, valueClass }: {
  label: string; value: string | number; sub?: ReactNode; valueClass?: string
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${valueClass ? ' ' + valueClass : ''}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

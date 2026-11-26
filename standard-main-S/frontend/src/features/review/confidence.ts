// Single source of truth for confidence tiers — reused by the dashboard,
// filters, and the badge component so thresholds never drift. Pure module
// (no components) so it's freely importable everywhere.

export interface ConfInfo {
  tier: 'green' | 'blue' | 'yellow' | 'red' | 'none'
  label: string
  color: string
  pct: number
}

/** Badge tier per the spec: 95–100 green, 85–94 blue, 70–84 yellow, <70 red. */
export function confidenceInfo(c: number): ConfInfo {
  const pct = Math.round(c * 100)
  if (c <= 0)     return { tier: 'none',   label: 'No score',  color: 'var(--text-muted)', pct: 0 }
  if (pct >= 95)  return { tier: 'green',  label: 'Very high', color: '#22c55e', pct }
  if (pct >= 85)  return { tier: 'blue',   label: 'High',      color: '#3b82f6', pct }
  if (pct >= 70)  return { tier: 'yellow', label: 'Medium',    color: '#eab308', pct }
  return             { tier: 'red',    label: 'Low',       color: '#ef4444', pct }
}

/** Coarse 3-bucket for the High / Medium / Low filter (>=85 / 70–84 / <70). */
export function confidenceBucket(c: number): 'high' | 'medium' | 'low' {
  const pct = Math.round(c * 100)
  if (pct >= 85) return 'high'
  if (pct >= 70) return 'medium'
  return 'low'
}

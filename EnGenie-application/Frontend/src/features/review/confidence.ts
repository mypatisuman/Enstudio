export interface ConfInfo {
  tier: 'green' | 'blue' | 'yellow' | 'red' | 'none';
  label: string;
  color: string;
  pct: number;
}

/** Badge tier per the spec: 95–100 green, 85–94 blue, 70–84 yellow, <70 red. */
export function confidenceInfo(c: number): ConfInfo {
  const pct = Math.round(c * 100);
  if (c <= 0) return { tier: 'none', label: 'No score', color: 'var(--text-muted)', pct: 0 };
  if (pct >= 95) return { tier: 'green', label: 'Very high', color: '#22c55e', pct };
  if (pct >= 85) return { tier: 'blue', label: 'High', color: '#3b82f6', pct };
  if (pct >= 70) return { tier: 'yellow', label: 'Medium', color: '#eab308', pct };
  return { tier: 'red', label: 'Low', color: '#ef4444', pct };
}

/** A node's confidence: its own score, else - for a symbol digitised from a
 *  drawing - how it was obtained: inferred from its loop (low, must be
 *  confirmed), untagged or a template placeholder (medium), read and placed
 *  on its printed text (very high), read at an estimated position (high).
 *  Anything else keeps the page's previous default. */
export function nodeConfidence(n: Record<string, any>, fallback = 0.9): number {
  if (typeof n.confidence === 'number') return n.confidence;
  if (n.inferred) return 0.55;
  if (n.recovered) return 0.7;
  if (n.untagged) return 0.65;
  if (n.placeholder) return 0.75;
  if (n.source === 'brownfield_vision') return n.snapped ? 0.96 : 0.88;
  return fallback;
}

/** Coarse 3-bucket for the High / Medium / Low filter (>=85 / 70–84 / <70). */
export function confidenceBucket(c: number): 'high' | 'medium' | 'low' {
  const pct = Math.round(c * 100);
  if (pct >= 85) return 'high';
  if (pct >= 70) return 'medium';
  return 'low';
}

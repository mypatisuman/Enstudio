// SVG path construction for pipe routes.
//
// Pure geometry, deliberately kept out of the edge components so it can be
// tested under plain `node` (which cannot load .tsx) and so every router on
// the canvas shares one corner style.
//
// Phase 3 note: there were three corner styles live at once — React Flow's
// getSmoothStepPath (rounded), BendableEdge's single elbow (rounded), and
// WaypointEdge (square). A sheet therefore mixed sharp and soft corners
// depending on which router handled each pipe, which reads as two unrelated
// line styles on the same drawing. This is now the single implementation.

import { RADIUS } from '../../../components/canvas/theme.ts'

export interface PathPoint { x: number; y: number }

/**
 * Rounds every elbow of a polyline: straight along each run, then a quadratic
 * through each corner instead of a hard angle.
 *
 * Malformed input is filtered rather than propagated — a NaN reaching an SVG
 * `d` attribute produces an invisible path with no error, which on a P&ID
 * means a silently missing pipe.
 */
export function roundedPolyline(pts: PathPoint[], r = RADIUS.pipe): string {
  const p = (pts ?? []).filter(q => q && Number.isFinite(q.x) && Number.isFinite(q.y))
  if (p.length < 2) return ''

  let d = `M ${p[0].x},${p[0].y}`
  for (let i = 1; i < p.length - 1; i++) {
    const a = p[i - 1], c = p[i], b = p[i + 1]
    const d1 = Math.hypot(c.x - a.x, c.y - a.y)
    const d2 = Math.hypot(b.x - c.x, b.y - c.y)
    // Coincident points have no corner to round.
    if (d1 === 0 || d2 === 0) { d += ` L ${c.x},${c.y}`; continue }
    // Never let the radius overshoot either adjoining run, or the curve would
    // bow past its own endpoint.
    const rr = Math.min(r, d1 / 2, d2 / 2)
    if (rr <= 0) { d += ` L ${c.x},${c.y}`; continue }
    const p1x = c.x + (a.x - c.x) / d1 * rr, p1y = c.y + (a.y - c.y) / d1 * rr
    const p2x = c.x + (b.x - c.x) / d2 * rr, p2y = c.y + (b.y - c.y) / d2 * rr
    d += ` L ${p1x},${p1y} Q ${c.x},${c.y} ${p2x},${p2y}`
  }
  const last = p[p.length - 1]
  return `${d} L ${last.x},${last.y}`
}

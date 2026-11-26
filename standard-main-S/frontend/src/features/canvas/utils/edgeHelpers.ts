import { createContext } from 'react'
import { MarkerType, type Node } from '@xyflow/react'
// Explicit .ts extension (allowed by tsconfig's allowImportingTsExtensions,
// same convention as extractedLayout.ts) so tests/canvas.test.ts can load
// this module under plain `node`, which won't resolve extensionless paths.
import { Theme, STROKE } from '../../../components/canvas/theme.ts'

// ── BendableEdge drag context ────────────────────────────────────────────────
// Dragging the corner (Draw mode, while the edge is selected) persists it as
// edges.extra_json.bend_x/y via this handler, so the custom route survives a reload.
export interface BendEdgeCtx {
  drawMode: boolean
  onBendDrag: (edgeId: string, source: string, target: string, clientX: number, clientY: number, commit: boolean) => void
}
export const BendEdgeContext = createContext<BendEdgeCtx | null>(null)

// ── Edge styles ───────────────────────────────────────────────────────────────

export function edgeStyle(kind: string): React.CSSProperties {
  switch ((kind ?? '').toLowerCase()) {
    case 'signal': return { stroke: Theme.signalPipe, strokeDasharray: '6 4', strokeWidth: STROKE.signal, opacity: 0.8 }
    case 'bypass': return { stroke: '#d97706', strokeDasharray: '5 3', strokeWidth: STROKE.pipe, opacity: 1 }
    case 'recycle': return { stroke: '#16a34a', strokeDasharray: '5 3', strokeWidth: STROKE.pipe, opacity: 1 }
    case 'utility': return { stroke: '#0f766e', strokeDasharray: '2 2', strokeWidth: STROKE.pipe, opacity: 1 }
    case 'assoc': return { stroke: '#1e293b', strokeDasharray: '3 2', strokeWidth: 1, opacity: 1 }
    default: return { stroke: Theme.processPipe, strokeWidth: STROKE.pipe, opacity: 1 }
  }
}
/**
 * Which edge component draws a connection.
 *
 * Phase 3: this used to be `return 'bendable'` unconditionally, which threw
 * away every extracted pipe route. `hasWaypointRoute` is the decision made by
 * features/canvas/utils/waypoints.ts::routeKindFor — kept as a parameter so
 * this stays a trivial mapping and the real logic remains testable in one
 * place. Callers with no route information keep the previous behaviour.
 */
export function edgeFlowType(_kind: string, hasWaypointRoute = false): string {
  return hasWaypointRoute ? 'waypoint' : 'bendable'
}

/**
 * Visual treatment for how well-established a connection is.
 *
 * Deliberately restrained — the phase brief asks for a clean internal
 * representation, not a UI redesign, and "accuracy before aesthetics". The
 * rule is only that an LLM edge must not read as deterministic and an
 * unaudited edge must not read as verified:
 *
 *   geometry   solid, full opacity     — deterministic, LLM-confirmed
 *   llm        solid, full opacity     — LLM-added; drawn the same as geometry
 *   unaudited  translucent + dotted    — never audited (PARTIAL run)
 *   unknown    unchanged               — pre-Phase-2 data / hand-drawn
 *
 * Returned as a style DELTA so it composes with edgeStyle(kind) without
 * overriding the line-type semantics (signal dashes, bypass colour, ...).
 */
export function trustStyle(trust: string): React.CSSProperties {
  switch (trust) {
    // 'llm' no longer dims the line. A confirmed connection is a confirmed
    // connection whichever stage established it, and the legend row that
    // explained the two shades was removed — leaving the canvas showing a
    // difference with nothing to account for it. Provenance is still recorded
    // on every edge (extra_json.provenance) for diagnosis and export.
    case 'unaudited': return { opacity: 0.55, strokeDasharray: '2 3' }
    default:          return {}
  }
}

// React Flow renders its own marker <defs> from this config (ids computed
// internally via getMarkerId) — a raw 'url(#id)' string is silently ignored,
// since React Flow always re-wraps edge.markerEnd through its own id scheme.
export function flowArrow(color: string = Theme.processPipe) {
  return { type: MarkerType.ArrowClosed, color, width: 10, height: 10 }
}
export const FLOW_ARROW = flowArrow()

// Phase 4: `nodes` may be passed as a Map. Callers that resolve handles for
// every edge (the rfEdges memo) hit this once per edge, and the two array
// scans made that O(nodes x edges) — 17.6 ms at 1000 nodes / 5000 edges, on
// top of the same scans the memo did for the symbol boxes. One-shot callers
// (add connection, branch a pipe) still pass the array; building a Map for a
// single lookup would be slower.
export function pickHandles(nodes: Node[] | Map<string, Node>, srcId: string, tgtId: string) {
  const byId = (id: string) => nodes instanceof Map ? nodes.get(id) : nodes.find(n => n.id === id)
  const src = byId(srcId)
  const tgt = byId(tgtId)
  if (!src || !tgt) return {}
  // Junction nodes carry a real width/height (16×16, set at creation) — use it
  // like any other node. An earlier version zeroed it out to "connect to the
  // center", but node.position is always the TOP-LEFT corner in React Flow, so
  // zeroing the size made tx/ty resolve to the junction's corner, not its
  // center — an 8px bias that flipped the axis decision on short hops and drew
  // an ugly hook instead of a straight/L line. Real size = correct center.
  const sw = src.measured?.width ?? (src.style?.width as number) ?? (src.width as number) ?? 80
  const sh = src.measured?.height ?? (src.style?.height as number) ?? (src.height as number) ?? 50
  const tw = tgt.measured?.width ?? (tgt.style?.width as number) ?? (tgt.width as number) ?? 80
  const th = tgt.measured?.height ?? (tgt.style?.height as number) ?? (tgt.height as number) ?? 50
  const sx = src.position.x + sw / 2
  const sy = src.position.y + sh / 2
  const tx = tgt.position.x + tw / 2
  const ty = tgt.position.y + th / 2
  const dx = tx - sx
  const dy = ty - sy
  const absDx = Math.abs(dx)
  const absDy = Math.abs(dy)

  // "Same vertical line" = centers within half the smaller symbol's width.
  // In that case always use top/bottom handles for a straight vertical line.
  const onSameVerticalLine = absDx <= Math.min(sw, tw) * 0.5
  if (onSameVerticalLine) {
    return dy >= 0
      ? { sourceHandle: 'sb', targetHandle: 'tt' }
      : { sourceHandle: 'st', targetHandle: 'tb' }
  }
  // "Same horizontal line" = centers within half the smaller symbol's height.
  // Only then do we use a straight horizontal connection (left/right handles).
  const onSameHorizontalLine = absDy <= Math.min(sh, th) * 0.5
  if (onSameHorizontalLine) {
    return dx >= 0
      ? { sourceHandle: 'sr', targetHandle: 'tl' }
      : { sourceHandle: 'sl', targetHandle: 'tr' }
  }
  // Any other case: the two symbols are offset on both axes (diagonal).
  // Decide handle orientation dynamically.
  const srcType = String(src.type ?? '')
  const tgtType = String(tgt.type ?? '')

  // Valves always prefer inline horizontal connections. Tanks adapt to the dominant offset.
  const srcPrefersVert = srcType.includes('valve') ? false : absDy > absDx
  const tgtPrefersVert = tgtType.includes('valve') ? false : absDy > absDx

  const sourceHandle = srcPrefersVert ? (dy < 0 ? 'st' : 'sb') : (dx < 0 ? 'sl' : 'sr')
  const targetHandle = tgtPrefersVert ? (dy >= 0 ? 'tt' : 'tb') : (dx >= 0 ? 'tl' : 'tr')

  return { sourceHandle, targetHandle }
}

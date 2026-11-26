// Waypoint sanitisation and routing selection.
//
// Phase 3. The extraction pipeline computes a real pipe route for every
// geometry-backed edge — connectivity_graph records which detected segments
// support the edge, _chain_pixel_segments walks their actual pixel path, and
// _snap_start/_snap_end seat the ends on the correct symbol face. All of that
// was persisted to edges.extra_json, read out by the Rust DTO, typed on the
// frontend... and then discarded, because edgeFlowType() returned 'bendable'
// unconditionally and every pipe was redrawn as a synthetic centre-to-centre
// elbow.
//
// This module is the gate between "extraction gave us a route" and "the
// canvas draws a synthetic one". It is deliberately pure and free of React so
// the decision is testable without a renderer.

import type { GraphEdge } from '../types'

/** A route point in normalised sheet space (0-1, top-left origin). */
export interface NormPoint { x: number; y: number }

/** Which edge component should draw this connection. */
export type RouteKind = 'waypoint' | 'bendable'

// Extraction emits normalised coordinates. Anything outside this window is a
// parsing or unit error, not a pipe on the sheet; a small overshoot is
// tolerated because _snap_start/_snap_end can seat an endpoint marginally
// outside the drawn area.
const MIN_COORD = -0.05
const MAX_COORD = 1.05

// Two interior points closer than this are the same corner reported twice —
// keeping both adds a zero-length hop that the orthogonaliser then turns into
// a visible stub. ~0.001 of a 4096px sheet is ~4px.
const DUPLICATE_TOL = 0.001

function isFinitePair(p: unknown): p is [number, number] {
  return (
    Array.isArray(p) && p.length >= 2 &&
    typeof p[0] === 'number' && typeof p[1] === 'number' &&
    Number.isFinite(p[0]) && Number.isFinite(p[1])
  )
}

function inRange(v: number): boolean {
  return v >= MIN_COORD && v <= MAX_COORD
}

/**
 * Turn raw `edge.waypoints` into the INTERIOR route points the canvas should
 * bend through, or [] when there is no usable route.
 *
 * The first and last stored points are the edge's own endpoints — the canvas
 * anchors to the live node handles instead, so those are dropped. What is left
 * is the set of real bends.
 *
 * Malformed input never throws: a non-array, a ragged row, a NaN, an Infinity,
 * a string, a null, or a coordinate outside the sheet all just fail the filter
 * and the edge falls back to interactive routing.
 */
export function sanitizeWaypoints(raw: unknown): NormPoint[] {
  if (!Array.isArray(raw) || raw.length < 2) {
    // < 2 means no usable geometry at all (empty or single point).
    // A 2-point array [start, end] is a valid straight pipe with no interior
    // bends — it is NOT discarded here. After slicing off both endpoints the
    // interior will be [], which the canvas renders as a direct connection.
    return []
  }

  const pts: NormPoint[] = []
  for (const p of raw) {
    if (!isFinitePair(p)) continue
    const [x, y] = p
    if (!inRange(x) || !inRange(y)) continue
    pts.push({ x, y })
  }
  // Need both endpoints plus at least one interior point to be worth using.
  if (pts.length < 3) return []

  // Drop the stored endpoints; the canvas anchors to the node handles.
  const interior = pts.slice(1, -1)

  // Collapse consecutive duplicates.
  const out: NormPoint[] = []
  for (const p of interior) {
    const prev = out[out.length - 1]
    if (prev && Math.abs(prev.x - p.x) < DUPLICATE_TOL &&
        Math.abs(prev.y - p.y) < DUPLICATE_TOL) {
      continue
    }
    out.push(p)
  }
  return out
}

/** A rendered node's box in flow pixels. */
export interface NodeBox { x1: number; y1: number; x2: number; y2: number }

/** Small slack around a node box: a bend this close adds nothing the handle
 *  does not already express, and drawing to it produces a visible hook. */
const CLIP_MARGIN = 6

function boxCentre(b: NodeBox) {
  return { x: (b.x1 + b.x2) / 2, y: (b.y1 + b.y2) / 2 }
}

function inBox(p: { x: number; y: number }, b: NodeBox, margin = CLIP_MARGIN) {
  return p.x >= b.x1 - margin && p.x <= b.x2 + margin &&
         p.y >= b.y1 - margin && p.y <= b.y2 + margin
}

/**
 * Which face of `b` a point outside it sits against, as a React Flow handle
 * suffix. Compared as a FRACTION of each half-extent so a wide, short symbol
 * does not always report left/right.
 *
 * `portsAreHorizontal` marks an INLINE two-port component — a valve, a
 * regulator, an orifice. Those have exactly two process ports, on the left and
 * right; the top is the actuator stem and the bottom is nothing. Anchoring a
 * pipe there draws it into the actuator, which reads as a line stopping in
 * mid-air just above the symbol. pickHandles has always applied this rule
 * ("Valves always prefer inline horizontal connections"); this is the same
 * constraint, restored for the route-derived path.
 */
function faceToward(
  b: NodeBox, p: { x: number; y: number }, portsAreHorizontal = false,
): string {
  const c = boxCentre(b)
  if (portsAreHorizontal) return p.x >= c.x ? 'r' : 'l'
  const hw = Math.max((b.x2 - b.x1) / 2, 1)
  const hh = Math.max((b.y2 - b.y1) / 2, 1)
  const rx = (p.x - c.x) / hw
  const ry = (p.y - c.y) / hh
  if (Math.abs(rx) >= Math.abs(ry)) return rx >= 0 ? 'r' : 'l'
  return ry >= 0 ? 'b' : 't'
}

export interface BuiltRoute {
  /** Interior bends, in flow pixels, that lie outside both symbols. */
  pts: { x: number; y: number }[]
  sourceHandle: string
  targetHandle: string
}

/**
 * Turn interior route points into a drawable route plus the handles it should
 * anchor to, or null when nothing usable survives.
 *
 * Two corrections live here, both found by measuring a real drawing (p-id-3,
 * 145 waypoint-routed edges):
 *
 * 1. CLIPPING. The canvas draws every symbol at a FIXED node size, while the
 *    stored route was traced against that symbol's real extent on the sheet —
 *    and extractedLayout then nudges nodes by up to ~100px for alignment and
 *    collision. A bend that comfortably cleared the drawn symbol can therefore
 *    land inside the rendered box: 57 of 145 target-side bends did. Drawing to
 *    such a point necessarily cuts through the symbol, and no choice of corner
 *    can avoid it. Leading and trailing points inside either box are dropped —
 *    the handle already expresses that position. This mirrors what extraction
 *    itself does with _clip_segments_to_symbols: geometry inside a symbol is
 *    not pipe.
 *
 * 2. HANDLES FROM THE SURVIVING ROUTE. The face each end anchors to is taken
 *    from the direction of the first/last SURVIVING bend relative to the
 *    RENDERED box — not from pickHandles' centre-to-centre guess (which knows
 *    nothing about the drawn pipe) and not from the raw stored endpoints
 *    (which describe a symbol extent the canvas no longer uses). This is what
 *    keeps the pipe meeting its symbol perpendicular to the correct face.
 */
export function buildRoute(
  interiorPixels: { x: number; y: number }[],
  srcBox: NodeBox,
  tgtBox: NodeBox,
  /** Marks an end as an inline two-port component (valve, regulator, ...)
   *  whose ports are on the left and right only. See faceToward. */
  ports: { srcHorizontal?: boolean; tgtHorizontal?: boolean } = {},
): BuiltRoute | null {
  let pts = interiorPixels.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y))

  // Drop leading points swallowed by the source symbol...
  let head = 0
  while (head < pts.length && inBox(pts[head], srcBox)) head++
  // ...and trailing points swallowed by the target symbol.
  let tail = pts.length
  while (tail > head && inBox(pts[tail - 1], tgtBox)) tail--
  pts = pts.slice(head, tail)

  // A bend inside the OTHER symbol is equally undrawable.
  pts = pts.filter(p => !inBox(p, srcBox) && !inBox(p, tgtBox))

  if (pts.length === 0) return null

  // A single bend between two endpoints the LAYOUT has already aligned is a
  // jog artifact, not a corner. Drop it and let the straight router draw the
  // run.
  //
  // Why it happens: YOLO (symbols) and U-Net (lines) do not agree to the
  // pixel on a component's stem centreline, so a dead-straight pipe is traced
  // with a small lateral kink. Extraction has its own straightener for this
  // (_chain_pixel_segments' _JOG_TOL), but it only fires when the STORED
  // endpoints already share an axis. extractedLayout then runs
  // snapAlignGroups, which forces connected near-collinear symbols onto a
  // shared centreline — so the canvas ends up having made the run exactly
  // straight (measured off-axis distance 0.0px) while still carrying a bend
  // 3-32px to one side, and draws a Z where the drawing has a straight line.
  //
  // Restricted to a SINGLE bend on purpose: one corner between two aligned
  // ports cannot describe anything but a jog, whereas a genuine detour that
  // leaves an axis and returns to it needs at least two.
  if (pts.length === 1) {
    const sc = boxCentre(srcBox)
    const tc = boxCentre(tgtBox)
    const dx = Math.abs(tc.x - sc.x)
    const dy = Math.abs(tc.y - sc.y)
    const w = Math.min(srcBox.x2 - srcBox.x1, tgtBox.x2 - tgtBox.x1)
    const h = Math.min(srcBox.y2 - srcBox.y1, tgtBox.y2 - tgtBox.y1)
    // "On the same line" reuses the half-extent rule pickHandles already
    // applies. The deviation bound is the symbol's OWN footprint on the
    // deviating axis: detector jitter comes from a stem-centreline mismatch,
    // so it scales with the symbol, not with the length of the run. Measured
    // jitter on real sheets topped out at 32px against 60px-wide nodes; a
    // bend further off than the symbol is wide is describing something real
    // and is kept.
    const jog =
      (dx <= w / 2 && Math.abs(pts[0].x - (sc.x + tc.x) / 2) <= w) ||
      (dy <= h / 2 && Math.abs(pts[0].y - (sc.y + tc.y) / 2) <= h)
    if (jog) return null
  }

  const sourceHandle = `s${faceToward(srcBox, pts[0], ports.srcHorizontal)}`
  const targetHandle = `t${faceToward(tgtBox, pts[pts.length - 1], ports.tgtHorizontal)}`

  // Square the first and last bend onto their anchor's axis when they are
  // within a few pixels of it. Detector jitter leaves a bend 4-8px off the
  // line the pipe actually runs on; without this the orthogonaliser dutifully
  // inserts a corner for that offset and draws a tiny stair-step right where
  // the pipe meets the symbol — e.g. (1312,746) -> (1421,746) -> (1421,741)
  // -> (1422,998) instead of a clean L. Only the BENDS move; the anchors are
  // where the pipe attaches and must not.
  //
  // AXIS_TOL matches line_detection_service._is_hv's own 8px orthogonality
  // tolerance rather than introducing another number.
  const AXIS_TOL = 8
  pts = pts.map(p => ({ ...p }))
  const sA = handleAnchor(srcBox, sourceHandle)
  const tA = handleAnchor(tgtBox, targetHandle)
  const first = pts[0]
  if (sourceHandle[1] === 'l' || sourceHandle[1] === 'r') {
    if (Math.abs(first.y - sA.y) <= AXIS_TOL) first.y = sA.y
  } else if (Math.abs(first.x - sA.x) <= AXIS_TOL) {
    first.x = sA.x
  }
  const last = pts[pts.length - 1]
  if (targetHandle[1] === 'l' || targetHandle[1] === 'r') {
    if (Math.abs(last.y - tA.y) <= AXIS_TOL) last.y = tA.y
  } else if (Math.abs(last.x - tA.x) <= AXIS_TOL) {
    last.x = tA.x
  }

  // Final check: can this route actually be drawn as orthogonal hops without
  // a corner landing inside a symbol? On a real drawing a handful of routes
  // have a symbol sitting squarely in the elbow between two bends, where BOTH
  // possible corners are inside it. There is no honest orthogonal path there,
  // so the edge falls back to the interactive router rather than being drawn
  // through the symbol.
  if (!routeIsDrawable(pts, srcBox, tgtBox, sourceHandle, targetHandle)) return null

  return { pts, sourceHandle, targetHandle }
}

/** Anchor point of a handle on its box, matching React Flow's placement. */
function handleAnchor(b: NodeBox, handle: string): { x: number; y: number } {
  const c = boxCentre(b)
  switch (handle[1]) {
    case 'l': return { x: b.x1, y: c.y }
    case 'r': return { x: b.x2, y: c.y }
    case 't': return { x: c.x, y: b.y1 }
    default:  return { x: c.x, y: b.y2 }
  }
}

/**
 * Replays WaypointEdge's corner rules and reports whether every inserted
 * corner stays outside both symbols. Kept beside buildRoute so the two cannot
 * drift: if the drawing rules there change, this must change with them.
 */
function routeIsDrawable(
  pts: { x: number; y: number }[], srcBox: NodeBox, tgtBox: NodeBox,
  sourceHandle: string, targetHandle: string,
): boolean {
  const EPS = 1.5
  const isVert = (h: string) => h[1] === 't' || h[1] === 'b'
  const strictlyIn = (p: { x: number; y: number }, b: NodeBox) =>
    p.x > b.x1 && p.x < b.x2 && p.y > b.y1 && p.y < b.y2
  const hits = (p: { x: number; y: number }) => strictlyIn(p, srcBox) || strictlyIn(p, tgtBox)

  const all = [handleAnchor(srcBox, sourceHandle), ...pts, handleAnchor(tgtBox, targetHandle)]
  for (let i = 1; i < all.length; i++) {
    const a = all[i - 1], b = all[i]
    if (!(Math.abs(a.x - b.x) > EPS && Math.abs(a.y - b.y) > EPS)) continue
    const isFirst = i === 1
    const isLast = i === all.length - 1
    const h = { x: b.x, y: a.y }   // horizontal-first corner
    const v = { x: a.x, y: b.y }   // vertical-first corner
    let corner: { x: number; y: number }
    if (isFirst) corner = isVert(sourceHandle) ? v : h
    else if (isLast) corner = isVert(targetHandle) ? h : v
    else corner = (hits(h) && !hits(v)) ? v : h
    if (hits(corner)) return false
  }
  return true
}

/**
 * Route selection, in the priority the phase brief requires:
 *
 *   extracted geometry  >  deterministic fallback  >  interactive fallback
 *
 * A user-dragged bend outranks the extracted route: the engineer looked at
 * the drawing and moved it deliberately, and BendableEdge is what makes that
 * corner draggable. Everything else with real interior geometry routes
 * through WaypointEdge.
 */
export function routeKindFor(
  edge: Pick<GraphEdge, 'waypoints' | 'bend_x' | 'bend_y'>,
  interior: NormPoint[],
  layoutMode: string,
): RouteKind {
  const hasUserBend =
    layoutMode === 'extracted' && edge.bend_x != null && edge.bend_y != null
  if (hasUserBend) return 'bendable'
  // Extracted routes are only meaningful in the layout that keeps nodes at
  // their extracted positions. Under dagre/process layout the nodes have been
  // moved, so a pixel-accurate route to where they used to be is worse than
  // an honest elbow.
  //
  // A straight pipe stores exactly [start, end] — 2 waypoints, 0 interior
  // bends. sanitizeWaypoints correctly returns [] interior for it, but the
  // old `interior.length > 0` guard then fell through to 'bendable', losing
  // the geometry entirely. Check the raw array too: if waypoints has ≥ 2
  // entries the extraction DID produce geometry and we should honour it.
  if (layoutMode === 'extracted') {
    const rawLen = Array.isArray(edge.waypoints) ? edge.waypoints.length : 0
    if (interior.length > 0 || rawLen >= 2) return 'waypoint'
  }
  return 'bendable'
}

/**
 * How a connection was established, collapsed to the four states the canvas
 * needs to distinguish. Keeping this as one function means the legend, the
 * styling and any future filter all agree on the classification.
 *
 *   'geometry'   deterministic: proposed by connectivity_graph, LLM-confirmed
 *   'llm'        added by the LLM against evidence geometry surfaced
 *   'unaudited'  geometric candidate LLM B never got to audit (PARTIAL run)
 *   'unknown'    pre-Phase-2 extraction, or a hand-drawn editor edge
 */
export type EdgeTrust = 'geometry' | 'llm' | 'unaudited' | 'unknown'

export function edgeTrust(
  edge: Pick<GraphEdge, 'provenance' | 'audited'>,
): EdgeTrust {
  // audited === false is the strongest statement available: nothing verified
  // this edge against the drawing. It outranks provenance, which would
  // otherwise report the same edge as 'geometry' and imply confirmation.
  if (edge.audited === false) return 'unaudited'
  if (edge.provenance === 'geometry') return 'geometry'
  if (edge.provenance === 'llm') return 'llm'
  return 'unknown'
}

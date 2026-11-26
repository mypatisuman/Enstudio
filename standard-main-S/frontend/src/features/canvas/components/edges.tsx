import { useContext, useRef } from 'react'
import {
  BaseEdge, getSmoothStepPath, Position,
  type EdgeProps,
} from '@xyflow/react'
import { Theme, STROKE, RADIUS } from '../../../components/canvas/theme'
import { BendEdgeContext } from '../utils/edgeHelpers'
import { roundedPolyline } from '../utils/pipePath.ts'

// ── BendableEdge — orthogonal 2-segment pipe with a draggable corner ─────────
// Default corner (no user edit yet) uses the same dominant-axis heuristic as
// the rest of the app's orthogonal routing.

/** Single-elbow case — the shape BendableEdge draws. The 3-point case of
 *  roundedPolyline, so the two cannot diverge. */
function roundedCornerPath(sx: number, sy: number, cx: number, cy: number, tx: number, ty: number, r = RADIUS.pipe): string {
  return roundedPolyline([{ x: sx, y: sy }, { x: cx, y: cy }, { x: tx, y: ty }], r)
}

export function BendableEdge({ id, source, target, sourceHandleId, targetHandleId, sourceX, sourceY, targetX, targetY, data, selected, style, markerEnd }: EdgeProps) {
  // Hooks must run unconditionally on every render — the S-curve branch
  // below returns early, so these were previously called only on some
  // renders of the same edge instance (e.g. before vs. after a bend is
  // set), which is a real hook-order violation. Hoisted here; neither hook
  // has a side effect on call, so this changes nothing observable.
  const ctx = useContext(BendEdgeContext)
  const dragging = useRef(false)
  const d = data as { bend?: { x: number; y: number }; routeVertical?: boolean } | undefined
  const bend = d?.bend

  // If no user bend is set, check if we need an S-curve (handles are parallel: both horizontal or both vertical).
  if (!bend && sourceHandleId && targetHandleId) {
    const isSrcHoriz = sourceHandleId === 'sl' || sourceHandleId === 'sr'
    const isTgtHoriz = targetHandleId === 'tl' || targetHandleId === 'tr'
    if (isSrcHoriz === isTgtHoriz) {
      const getPos = (h: string) =>
        h === 'sl' || h === 'tl' ? Position.Left :
          h === 'sr' || h === 'tr' ? Position.Right :
            h === 'st' || h === 'tt' ? Position.Top : Position.Bottom

      const [path] = getSmoothStepPath({
        sourceX, sourceY, sourcePosition: getPos(sourceHandleId),
        targetX, targetY, targetPosition: getPos(targetHandleId),
        borderRadius: RADIUS.pipe
      })
      return (
        <BaseEdge path={path} markerEnd={markerEnd}
          style={{ ...style, strokeWidth: STROKE.pipe, stroke: selected ? Theme.selection : (style?.stroke ?? Theme.processPipe) }} />
      )
    }
  }

  // routeVertical is set by pickHandles and passed through edge data, so the
  // elbow corner always matches the handle selection.  Falls back to a
  // position heuristic only when the flag is absent.
  let corner = bend ?? (
    d?.routeVertical === true ? { x: sourceX, y: targetY } :   // vertical-first: up/down then horizontal
      d?.routeVertical === false ? { x: targetX, y: sourceY } :   // horizontal-first: left/right then vertical
        // Fallback when no routing flag — position-based heuristic
        Math.abs(targetX - sourceX) >= Math.abs(targetY - sourceY)
          ? { x: targetX, y: sourceY }
          : { x: sourceX, y: targetY }
  )
  // If the last segment (corner→target) is shorter than the arrow marker,
  // the arrowhead renders at a wrong angle. Flip the L-direction so the
  // short stub comes first and the arrow rides on the longer segment.
  if (!bend) {
    const lastLen = Math.hypot(targetX - corner.x, targetY - corner.y)
    if (lastLen > 0 && lastLen < 12) {
      corner = { x: sourceX + targetX - corner.x, y: sourceY + targetY - corner.y }
    }
  }
  const path = roundedCornerPath(sourceX, sourceY, corner.x, corner.y, targetX, targetY)

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd}
        style={{ strokeLinecap: 'round', strokeLinejoin: 'round', ...style }} />
      {selected && ctx?.drawMode && (
        <circle
          cx={corner.x} cy={corner.y} r={6}
          fill={Theme.selection} stroke="#fff" strokeWidth={1.5}
          style={{ cursor: 'move', pointerEvents: 'all' }}
          onPointerDown={e => {
            e.stopPropagation()
              ; (e.target as Element).setPointerCapture(e.pointerId)
            dragging.current = true
          }}
          onPointerMove={e => {
            if (!dragging.current) return
            ctx.onBendDrag(id, source, target, e.clientX, e.clientY, false)
          }}
          onPointerUp={e => {
            if (!dragging.current) return
            dragging.current = false
            ctx.onBendDrag(id, source, target, e.clientX, e.clientY, true)
          }}
        />
      )}
    </>
  )
}

// WaypointEdge — draws the real traced pipe route (parallel runs, crossovers,
// jogs) instead of a synthetic center-to-center elbow. `data.pts` are the
// INTERIOR route points in flow pixels (node-centre endpoints dropped); the
// path anchors to the actual source/target handles so it never truncates —
// which was the reason waypoints were disabled before.
//
// Phase 3: this component existed and was registered in EDGE_TYPES_MAP but
// was never instantiated, because edgeFlowType() returned 'bendable' for
// every edge. It is now the route for any extracted edge that has real
// interior geometry (see utils/waypoints.ts).
//
// Robustness: `pts` arrives from extraction data that this component does not
// control, so every point is re-checked here even though sanitizeWaypoints
// already filtered it. A NaN reaching an SVG `d` attribute produces an
// invisible path and no error, which is the worst possible failure mode —
// silently missing pipes. Anything non-finite is dropped, and an edge left
// with no usable interior points degrades to a straight handle-to-handle
// line rather than rendering nothing.
export function WaypointEdge({ id, sourceX, sourceY, targetX, targetY,
                               sourceHandleId, targetHandleId,
                               data, style, markerEnd }: EdgeProps) {
  const rawPts = (data as { pts?: { x: number; y: number }[] } | undefined)?.pts
  const pts = Array.isArray(rawPts)
    ? rawPts.filter(p =>
        p != null && Number.isFinite(p.x) && Number.isFinite(p.y))
    : []

  // Endpoints come from React Flow; if it hands us a non-finite one there is
  // nothing sane to draw.
  if (![sourceX, sourceY, targetX, targetY].every(Number.isFinite)) return null

  const all = [{ x: sourceX, y: sourceY }, ...pts, { x: targetX, y: targetY }]

  // Orthogonalise: P&ID pipes are never diagonal, but the CV segment-chaining
  // bridges gaps between detected segments with slanted lines, so every hop
  // that is diagonal needs a corner inserted.
  //
  // WHICH corner matters at the two ends, and getting it wrong is what made
  // pipes appear to run through their symbols instead of meeting them. A
  // handle sits on one FACE of the symbol, so the pipe has to leave (and
  // arrive) perpendicular to that face:
  //
  //   left/right handle  -> the adjoining segment must be HORIZONTAL
  //   top/bottom handle  -> the adjoining segment must be VERTICAL
  //
  // Blindly inserting the corner at (b.x, a.y) — always horizontal-first —
  // meant an edge anchored on a top or bottom handle set off sideways across
  // the symbol before turning, putting the corner INSIDE the symbol box on
  // 39% of source ends and 29% of target ends of a real drawing (p-id-3).
  //
  // Interior hops keep the horizontal-first default: they run between real
  // detected bends and are almost always already axis-aligned.
  const EPS = 1.5
  const isVertical = (h: string | null | undefined) => h === 'st' || h === 'sb' || h === 'tt' || h === 'tb'
  const srcVertical = isVertical(sourceHandleId)
  const tgtVertical = isVertical(targetHandleId)

  // Symbol boxes, so an INTERIOR corner can avoid cutting through one. The
  // end corners are already handled by the axis rules above; this only
  // affects hops between two real bends where a symbol happens to sit in the
  // elbow. Optional — without them the horizontal-first default applies.
  const boxes = (data as { boxes?: { x1: number; y1: number; x2: number; y2: number }[] } | undefined)?.boxes
  const hitsBox = (p: { x: number; y: number }) =>
    Array.isArray(boxes) && boxes.some(b =>
      p.x > b.x1 && p.x < b.x2 && p.y > b.y1 && p.y < b.y2)

  // Build the full vertex list first, then draw it with the SAME rounded
  // corners BendableEdge uses, so a sheet does not mix sharp and soft elbows
  // depending on which router handled each pipe.
  const verts: { x: number; y: number }[] = [all[0]]
  for (let i = 1; i < all.length; i++) {
    const a = verts[verts.length - 1], b = all[i]
    const diagonal = Math.abs(a.x - b.x) > EPS && Math.abs(a.y - b.y) > EPS
    if (diagonal) {
      const isFirst = i === 1
      const isLast = i === all.length - 1
      let verticalFirst: boolean
      if (isFirst) {
        // Leave the source along its handle's own axis.
        verticalFirst = srcVertical
      } else if (isLast) {
        // Arrive at the target along its handle's axis: to finish with a
        // horizontal segment we must travel vertically first, and vice versa.
        verticalFirst = !tgtVertical
      } else {
        // Interior elbow: horizontal-first unless that corner lands in a
        // symbol, in which case the other elbow is the better of the two.
        verticalFirst = hitsBox({ x: b.x, y: a.y }) && !hitsBox({ x: a.x, y: b.y })
      }
      verts.push(verticalFirst ? { x: a.x, y: b.y } : { x: b.x, y: a.y })
    }
    verts.push(b)
  }
  return <BaseEdge id={id} path={roundedPolyline(verts)} markerEnd={markerEnd}
    style={{ strokeLinejoin: 'round', ...style }} />
}

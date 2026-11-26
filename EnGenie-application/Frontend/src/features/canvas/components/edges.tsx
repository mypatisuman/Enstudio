import React, { useContext, useRef } from 'react';
import {
  BaseEdge, getSmoothStepPath, Position,
  type EdgeProps,
} from '@xyflow/react';
import { Theme, STROKE, RADIUS } from '../../../components/canvas/theme';
import { BendEdgeContext } from '../utils/edgeHelpers';
import { roundedPolyline } from '../utils/pipePath';

function roundedCornerPath(sx: number, sy: number, cx: number, cy: number, tx: number, ty: number, r = RADIUS.pipe): string {
  return roundedPolyline([{ x: sx, y: sy }, { x: cx, y: cy }, { x: tx, y: ty }], r);
}

/** The printed line number (or size / spec) of a connection, set along the
 *  pipe the way it is printed on the drawing. */
export function PipeLabel({ x, y, text, vertical = false }: { x: number; y: number; text?: string; vertical?: boolean }) {
  if (!text || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  const w = text.length * 6.2 + 8;
  return (
    <g transform={`translate(${x},${y})${vertical ? ' rotate(-90)' : ''}`} style={{ pointerEvents: 'none' }}>
      <rect x={-w / 2} y={-17} width={w} height={13} rx={3} fill="#050914" fillOpacity={0.8} />
      <text x={0} y={-7} textAnchor="middle" fontSize={10} fontFamily="ui-monospace, monospace" fill="#fbbf24">
        {text}
      </text>
    </g>
  );
}

/** Midpoint of the longer leg of a source -> corner -> target route. */
function labelSpot(sx: number, sy: number, cx: number, cy: number, tx: number, ty: number) {
  const first = Math.hypot(cx - sx, cy - sy), second = Math.hypot(tx - cx, ty - cy);
  const [ax, ay, bx, by] = first >= second ? [sx, sy, cx, cy] : [cx, cy, tx, ty];
  return { x: (ax + bx) / 2, y: (ay + by) / 2, vertical: Math.abs(by - ay) > Math.abs(bx - ax) };
}

export function BendableEdge({ id, source, target, sourceHandleId, targetHandleId, sourceX, sourceY, targetX, targetY, data, selected, style, markerEnd }: EdgeProps) {
  const ctx = useContext(BendEdgeContext);
  const dragging = useRef(false);
  const d = data as { bend?: { x: number; y: number }; routeVertical?: boolean; label?: string } | undefined;
  const bend = d?.bend;

  if (!bend && sourceHandleId && targetHandleId) {
    const isSrcHoriz = sourceHandleId === 'sl' || sourceHandleId === 'sr';
    const isTgtHoriz = targetHandleId === 'tl' || targetHandleId === 'tr';
    if (isSrcHoriz === isTgtHoriz) {
      const getPos = (h: string) =>
        h === 'sl' || h === 'tl' ? Position.Left :
          h === 'sr' || h === 'tr' ? Position.Right :
            h === 'st' || h === 'tt' ? Position.Top : Position.Bottom;

      const [path, lx, ly] = getSmoothStepPath({
        sourceX, sourceY, sourcePosition: getPos(sourceHandleId),
        targetX, targetY, targetPosition: getPos(targetHandleId),
        borderRadius: RADIUS.pipe
      });
      return (
        <>
          <BaseEdge path={path} markerEnd={markerEnd}
            style={{ ...style, strokeWidth: style?.strokeWidth ?? STROKE.pipe, stroke: selected ? Theme.selection : (style?.stroke ?? Theme.processPipe) }} />
          <PipeLabel x={lx} y={ly} text={d?.label}
            vertical={isSrcHoriz ? false : Math.abs(targetY - sourceY) > Math.abs(targetX - sourceX)} />
        </>
      );
    }
  }

  let corner = bend ?? (
    d?.routeVertical === true ? { x: sourceX, y: targetY } :
      d?.routeVertical === false ? { x: targetX, y: sourceY } :
        Math.abs(targetX - sourceX) >= Math.abs(targetY - sourceY)
          ? { x: targetX, y: sourceY }
          : { x: sourceX, y: targetY }
  );

  if (!bend) {
    const lastLen = Math.hypot(targetX - corner.x, targetY - corner.y);
    if (lastLen > 0 && lastLen < 12) {
      corner = { x: sourceX + targetX - corner.x, y: sourceY + targetY - corner.y };
    }
  }
  const path = roundedCornerPath(sourceX, sourceY, corner.x, corner.y, targetX, targetY);
  const spot = labelSpot(sourceX, sourceY, corner.x, corner.y, targetX, targetY);

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd}
        style={{ strokeLinecap: 'round', strokeLinejoin: 'round', ...style }} />
      <PipeLabel x={spot.x} y={spot.y} text={d?.label} vertical={spot.vertical} />
      {selected && ctx?.drawMode && (
        <circle
          cx={corner.x} cy={corner.y} r={6}
          fill={Theme.selection} stroke="#fff" strokeWidth={1.5}
          style={{ cursor: 'move', pointerEvents: 'all' }}
          onPointerDown={e => {
            e.stopPropagation();
            (e.target as Element).setPointerCapture(e.pointerId);
            dragging.current = true;
          }}
          onPointerMove={e => {
            if (!dragging.current) return;
            ctx.onBendDrag(id, source, target, e.clientX, e.clientY, false);
          }}
          onPointerUp={e => {
            if (!dragging.current) return;
            dragging.current = false;
            ctx.onBendDrag(id, source, target, e.clientX, e.clientY, true);
          }}
        />
      )}
    </>
  );
}

export function WaypointEdge({ id, sourceX, sourceY, targetX, targetY,
                               sourceHandleId, targetHandleId,
                               data, style, markerEnd }: EdgeProps) {
  const rawPts = (data as { pts?: { x: number; y: number }[] } | undefined)?.pts;
  const pts = Array.isArray(rawPts)
    ? rawPts.filter(p =>
        p != null && Number.isFinite(p.x) && Number.isFinite(p.y))
    : [];

  if (![sourceX, sourceY, targetX, targetY].every(Number.isFinite)) return null;

  const all = [{ x: sourceX, y: sourceY }, ...pts, { x: targetX, y: targetY }];

  const EPS = 1.5;
  const isVertical = (h: string | null | undefined) => h === 'st' || h === 'sb' || h === 'tt' || h === 'tb';
  const srcVertical = isVertical(sourceHandleId);
  const tgtVertical = isVertical(targetHandleId);

  const boxes = (data as { boxes?: { x1: number; y1: number; x2: number; y2: number }[] } | undefined)?.boxes;
  const hitsBox = (p: { x: number; y: number }) =>
    Array.isArray(boxes) && boxes.some(b =>
      p.x > b.x1 && p.x < b.x2 && p.y > b.y1 && p.y < b.y2);

  const verts: { x: number; y: number }[] = [all[0]];
  for (let i = 1; i < all.length; i++) {
    const a = verts[verts.length - 1], b = all[i];
    const diagonal = Math.abs(a.x - b.x) > EPS && Math.abs(a.y - b.y) > EPS;
    if (diagonal) {
      const isFirst = i === 1;
      const isLast = i === all.length - 1;
      let verticalFirst: boolean;
      if (isFirst) {
        verticalFirst = srcVertical;
      } else if (isLast) {
        verticalFirst = !tgtVertical;
      } else {
        verticalFirst = hitsBox({ x: b.x, y: a.y }) && !hitsBox({ x: a.x, y: b.y });
      }
      verts.push(verticalFirst ? { x: a.x, y: b.y } : { x: b.x, y: a.y });
    }
    verts.push(b);
  }
  return <BaseEdge id={id} path={roundedPolyline(verts)} markerEnd={markerEnd}
    style={{ strokeLinejoin: 'round', ...style }} />;
}

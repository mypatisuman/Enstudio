// Waypoint sanitisation and routing selection.
import type { GraphEdge } from '../types';

/** A route point in normalised sheet space (0-1, top-left origin). */
export interface NormPoint { x: number; y: number }

/** Which edge component should draw this connection. */
export type RouteKind = 'waypoint' | 'bendable';

const MIN_COORD = -0.05;
const MAX_COORD = 1.05;
const DUPLICATE_TOL = 0.001;

function isFinitePair(p: unknown): p is [number, number] {
  return (
    Array.isArray(p) && p.length >= 2 &&
    typeof p[0] === 'number' && typeof p[1] === 'number' &&
    Number.isFinite(p[0]) && Number.isFinite(p[1])
  );
}

function inRange(v: number): boolean {
  return v >= MIN_COORD && v <= MAX_COORD;
}

export function sanitizeWaypoints(raw: unknown): NormPoint[] {
  if (!Array.isArray(raw) || raw.length < 2) {
    return [];
  }

  const pts: NormPoint[] = [];
  for (const p of raw) {
    if (!isFinitePair(p)) continue;
    const [x, y] = p;
    if (!inRange(x) || !inRange(y)) continue;
    pts.push({ x, y });
  }
  if (pts.length < 3) return [];

  const interior = pts.slice(1, -1);
  const out: NormPoint[] = [];
  for (const p of interior) {
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.x - p.x) < DUPLICATE_TOL &&
        Math.abs(prev.y - p.y) < DUPLICATE_TOL) {
      continue;
    }
    out.push(p);
  }
  return out;
}

/** A rendered node's box in flow pixels. */
export interface NodeBox { x1: number; y1: number; x2: number; y2: number }

const CLIP_MARGIN = 6;

function boxCentre(b: NodeBox) {
  return { x: (b.x1 + b.x2) / 2, y: (b.y1 + b.y2) / 2 };
}

function inBox(p: { x: number; y: number }, b: NodeBox, margin = CLIP_MARGIN) {
  return p.x >= b.x1 - margin && p.x <= b.x2 + margin &&
         p.y >= b.y1 - margin && p.y <= b.y2 + margin;
}

function faceToward(
  b: NodeBox, p: { x: number; y: number }, portsAreHorizontal = false,
): string {
  const c = boxCentre(b);
  if (portsAreHorizontal) return p.x >= c.x ? 'r' : 'l';
  const hw = Math.max((b.x2 - b.x1) / 2, 1);
  const hh = Math.max((b.y2 - b.y1) / 2, 1);
  const rx = (p.x - c.x) / hw;
  const ry = (p.y - c.y) / hh;
  if (Math.abs(rx) >= Math.abs(ry)) return rx >= 0 ? 'r' : 'l';
  return ry >= 0 ? 'b' : 't';
}

export interface BuiltRoute {
  pts: { x: number; y: number }[];
  sourceHandle: string;
  targetHandle: string;
}

export function buildRoute(
  interiorPixels: { x: number; y: number }[],
  srcBox: NodeBox,
  tgtBox: NodeBox,
  ports: { srcHorizontal?: boolean; tgtHorizontal?: boolean } = {},
): BuiltRoute | null {
  let pts = interiorPixels.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));

  let head = 0;
  while (head < pts.length && inBox(pts[head], srcBox)) head++;
  let tail = pts.length;
  while (tail > head && inBox(pts[tail - 1], tgtBox)) tail--;
  pts = pts.slice(head, tail);

  pts = pts.filter(p => !inBox(p, srcBox) && !inBox(p, tgtBox));

  if (pts.length === 0) return null;

  if (pts.length === 1) {
    const sc = boxCentre(srcBox);
    const tc = boxCentre(tgtBox);
    const dx = Math.abs(tc.x - sc.x);
    const dy = Math.abs(tc.y - sc.y);
    const w = Math.min(srcBox.x2 - srcBox.x1, tgtBox.x2 - tgtBox.x1);
    const h = Math.min(srcBox.y2 - srcBox.y1, tgtBox.y2 - tgtBox.y1);
    const jog =
      (dx <= w / 2 && Math.abs(pts[0].x - (sc.x + tc.x) / 2) <= w) ||
      (dy <= h / 2 && Math.abs(pts[0].y - (sc.y + tc.y) / 2) <= h);
    if (jog) return null;
  }

  const sourceHandle = `s${faceToward(srcBox, pts[0], ports.srcHorizontal)}`;
  const targetHandle = `t${faceToward(tgtBox, pts[pts.length - 1], ports.tgtHorizontal)}`;

  const AXIS_TOL = 8;
  pts = pts.map(p => ({ ...p }));
  const sA = handleAnchor(srcBox, sourceHandle);
  const tA = handleAnchor(tgtBox, targetHandle);
  const first = pts[0];
  if (sourceHandle[1] === 'l' || sourceHandle[1] === 'r') {
    if (Math.abs(first.y - sA.y) <= AXIS_TOL) first.y = sA.y;
  } else if (Math.abs(first.x - sA.x) <= AXIS_TOL) {
    first.x = sA.x;
  }
  const last = pts[pts.length - 1];
  if (targetHandle[1] === 'l' || targetHandle[1] === 'r') {
    if (Math.abs(last.y - tA.y) <= AXIS_TOL) last.y = tA.y;
  } else if (Math.abs(last.x - tA.x) <= AXIS_TOL) {
    last.x = tA.x;
  }

  if (!routeIsDrawable(pts, srcBox, tgtBox, sourceHandle, targetHandle)) return null;

  return { pts, sourceHandle, targetHandle };
}

function handleAnchor(b: NodeBox, handle: string): { x: number; y: number } {
  const c = boxCentre(b);
  switch (handle[1]) {
    case 'l': return { x: b.x1, y: c.y };
    case 'r': return { x: b.x2, y: c.y };
    case 't': return { x: c.x, y: b.y1 };
    default:  return { x: c.x, y: b.y2 };
  }
}

function routeIsDrawable(
  pts: { x: number; y: number }[], srcBox: NodeBox, tgtBox: NodeBox,
  sourceHandle: string, targetHandle: string,
): boolean {
  const EPS = 1.5;
  const isVert = (h: string) => h[1] === 't' || h[1] === 'b';
  const strictlyIn = (p: { x: number; y: number }, b: NodeBox) =>
    p.x > b.x1 && p.x < b.x2 && p.y > b.y1 && p.y < b.y2;
  const hits = (p: { x: number; y: number }) => strictlyIn(p, srcBox) || strictlyIn(p, tgtBox);

  const all = [handleAnchor(srcBox, sourceHandle), ...pts, handleAnchor(tgtBox, targetHandle)];
  for (let i = 1; i < all.length; i++) {
    const a = all[i - 1], b = all[i];
    if (!(Math.abs(a.x - b.x) > EPS && Math.abs(a.y - b.y) > EPS)) continue;
    const isFirst = i === 1;
    const isLast = i === all.length - 1;
    const h = { x: b.x, y: a.y };
    const v = { x: a.x, y: b.y };
    let corner: { x: number; y: number };
    if (isFirst) corner = isVert(sourceHandle) ? v : h;
    else if (isLast) corner = isVert(targetHandle) ? h : v;
    else corner = (hits(h) && !hits(v)) ? v : h;
    if (hits(corner)) return false;
  }
  return true;
}

export function routeKindFor(
  edge: Pick<GraphEdge, 'waypoints' | 'bend_x' | 'bend_y'>,
  interior: NormPoint[],
  layoutMode: string,
): RouteKind {
  const hasUserBend =
    layoutMode === 'extracted' && edge.bend_x != null && edge.bend_y != null;
  if (hasUserBend) return 'bendable';
  if (layoutMode === 'extracted') {
    const rawLen = Array.isArray(edge.waypoints) ? edge.waypoints.length : 0;
    if (interior.length > 0 || rawLen >= 2) return 'waypoint';
  }
  return 'bendable';
}

export type EdgeTrust = 'geometry' | 'llm' | 'unaudited' | 'unknown';

export function edgeTrust(
  edge: Pick<GraphEdge, 'provenance' | 'audited'>,
): EdgeTrust {
  if (edge.audited === false) return 'unaudited';
  if (edge.provenance === 'geometry') return 'geometry';
  if (edge.provenance === 'llm') return 'llm';
  return 'unknown';
}

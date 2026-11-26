import React, { createContext } from 'react';
import { MarkerType, type Node } from '@xyflow/react';
import { Theme, STROKE } from '../../../components/canvas/theme';

export interface BendEdgeCtx {
  drawMode: boolean;
  onBendDrag: (edgeId: string, source: string, target: string, clientX: number, clientY: number, commit: boolean) => void;
}
export const BendEdgeContext = createContext<BendEdgeCtx | null>(null);

export function edgeStyle(kind: string): React.CSSProperties {
  switch ((kind ?? '').toLowerCase()) {
    case 'signal': return { stroke: Theme.signalPipe, strokeDasharray: '6 4', strokeWidth: STROKE.signal, opacity: 0.8 };
    // an instrument tapping a line or valve (ISA impulse line): short dots
    case 'impulse': return { stroke: '#22d3ee', strokeDasharray: '1 4', strokeWidth: STROKE.signal, opacity: 0.9, strokeLinecap: 'round' };
    case 'bypass': return { stroke: '#d97706', strokeDasharray: '5 3', strokeWidth: STROKE.pipe, opacity: 1 };
    case 'recycle': return { stroke: '#16a34a', strokeDasharray: '5 3', strokeWidth: STROKE.pipe, opacity: 1 };
    case 'utility': return { stroke: '#0f766e', strokeDasharray: '2 2', strokeWidth: STROKE.pipe, opacity: 1 };
    case 'assoc': return { stroke: '#1e293b', strokeDasharray: '3 2', strokeWidth: 1, opacity: 1 };
    default: return { stroke: Theme.processPipe, strokeWidth: STROKE.pipe, opacity: 1 };
  }
}

export function edgeFlowType(_kind: string, hasWaypointRoute = false): string {
  return hasWaypointRoute ? 'waypoint' : 'bendable';
}

export function trustStyle(trust: string): React.CSSProperties {
  switch (trust) {
    case 'unaudited': return { opacity: 0.55, strokeDasharray: '2 3' };
    default:          return {};
  }
}

export function flowArrow(color: string = Theme.processPipe) {
  return { type: MarkerType.ArrowClosed, color, width: 10, height: 10 };
}
export const FLOW_ARROW = flowArrow();

export function pickHandles(nodes: Node[] | Map<string, Node>, srcId: string, tgtId: string) {
  const byId = (id: string) => nodes instanceof Map ? nodes.get(id) : nodes.find(n => n.id === id);
  const src = byId(srcId);
  const tgt = byId(tgtId);
  if (!src || !tgt) return {};

  const sw = src.measured?.width ?? (src.style?.width as number) ?? (src.width as number) ?? 80;
  const sh = src.measured?.height ?? (src.style?.height as number) ?? (src.height as number) ?? 50;
  const tw = tgt.measured?.width ?? (tgt.style?.width as number) ?? (tgt.width as number) ?? 80;
  const th = tgt.measured?.height ?? (tgt.style?.height as number) ?? (tgt.height as number) ?? 50;
  const sx = src.position.x + sw / 2;
  const sy = src.position.y + sh / 2;
  const tx = tgt.position.x + tw / 2;
  const ty = tgt.position.y + th / 2;
  const dx = tx - sx;
  const dy = ty - sy;
  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);

  const onSameVerticalLine = absDx <= Math.min(sw, tw) * 0.5;
  if (onSameVerticalLine) {
    return dy >= 0
      ? { sourceHandle: 'sb', targetHandle: 'tt' }
      : { sourceHandle: 'st', targetHandle: 'tb' };
  }

  const onSameHorizontalLine = absDy <= Math.min(sh, th) * 0.5;
  if (onSameHorizontalLine) {
    return dx >= 0
      ? { sourceHandle: 'sr', targetHandle: 'tl' }
      : { sourceHandle: 'sl', targetHandle: 'tr' };
  }

  const srcType = String(src.type ?? '');
  const tgtType = String(tgt.type ?? '');

  const srcPrefersVert = srcType.includes('valve') ? false : absDy > absDx;
  const tgtPrefersVert = tgtType.includes('valve') ? false : absDy > absDx;

  const sourceHandle = srcPrefersVert ? (dy < 0 ? 'st' : 'sb') : (dx < 0 ? 'sl' : 'sr');
  const targetHandle = tgtPrefersVert ? (dy >= 0 ? 'tt' : 'tb') : (dx >= 0 ? 'tl' : 'tr');

  return { sourceHandle, targetHandle };
}

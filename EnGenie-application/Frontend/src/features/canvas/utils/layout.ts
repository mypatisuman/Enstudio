import Dagre from '@dagrejs/dagre';
import { getNodeType, getNodeSize } from '../../../components/canvas/ISANodes';
import { isOffPage } from '../../../domain/isa/instrument';
import { normalizeGraphNodes } from '../../../domain/graph/normalize';
import type { GraphNode, GraphEdge, GraphData } from '../types';

export function normalizeGraph(g: GraphData): GraphData {
  if (g.nodes) {
    normalizeGraphNodes(g.nodes as any);
  }
  return g;
}

export function nodeSize(kind: string, lbl: string, softCount = 0, category = ''): { w: number; h: number } {
  const type = getNodeType(kind, lbl, isOffPage(kind, lbl, category));
  if (type === 'offpage') {
    const cleaned = (lbl || '').replace(/^off_page_?/i, '');
    const shown = cleaned.match(/\d{2,}-\d+-\d+(?:-\S+)?/)?.[0] ?? cleaned;
    const w = Math.max(96, Math.min(280, shown.length * 6 + 36));
    return { w, h: 40 };
  }
  return getNodeSize(type, softCount);
}

export function buildAssocEdges(nodes: GraphNode[]): GraphEdge[] {
  const labToId = new Map(nodes.map(n => [n.label, n.id]));
  const out: GraphEdge[] = [];
  nodes.forEach(n => {
    if (!n.equipment_ref) return;
    const eq = labToId.get(n.equipment_ref);
    if (eq && eq !== n.id) out.push({ source: eq, target: n.id, kind: 'assoc' });
  });
  return out;
}

export function connectedSet(topo: GraphEdge[], assoc: GraphEdge[]): Set<string> {
  const ids = new Set<string>();
  for (const e of [...topo, ...assoc]) {
    if (e.source) ids.add(e.source);
    if (e.target) ids.add(e.target);
  }
  return ids;
}

export function dagreLayout(
  nodes: GraphNode[],
  topo: GraphEdge[],
  assoc: GraphEdge[],
  softCounts: Map<string, number>,
): Map<string, { x: number; y: number }> {
  const g = new Dagre.graphlib.Graph({ multigraph: true });
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'LR', nodesep: 120, ranksep: 200, edgesep: 40, marginx: 48, marginy: 48 });
  const ids = new Set(nodes.map(n => n.id));
  nodes.forEach(n => {
    const { w, h } = nodeSize(n.type ?? n.kind, n.label, softCounts.get(n.id) ?? 0);
    g.setNode(n.id, { width: w, height: h });
  });
  topo.forEach((e, i) => {
    if (ids.has(e.source) && ids.has(e.target))
      g.setEdge(e.source, e.target, { weight: 2, minlen: 2 }, `t${i}`);
  });
  assoc.forEach(e => {
    if (ids.has(e.source) && ids.has(e.target))
      g.setEdge(e.source, e.target, { weight: 1, minlen: 2 }, `a${e.target}`);
  });
  Dagre.layout(g);
  const pos = new Map<string, { x: number; y: number }>();
  nodes.forEach(n => {
    const p = g.node(n.id);
    if (p) {
      const { w, h } = nodeSize(n.type ?? n.kind, n.label, softCounts.get(n.id) ?? 0);
      pos.set(n.id, { x: p.x - w / 2, y: p.y - h / 2 });
    }
  });
  return pos;
}

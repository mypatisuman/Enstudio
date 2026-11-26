export interface IntegrityReport {
  ok: boolean;
  duplicateNodeIds: string[];
  duplicateEdgeIds: string[];
  danglingEdges: { id: string; source: string; target: string; missing: string[] }[];
  selfLoops: string[];
  invalidPositions: string[];
}

interface MinNode { id: string; position?: { x: number; y: number } }
interface MinEdge { id: string; source: string; target: string }

export function checkGraphIntegrity(
  nodes: MinNode[], edges: MinEdge[],
): IntegrityReport {
  const seenNode = new Set<string>();
  const duplicateNodeIds: string[] = [];
  const invalidPositions: string[] = [];
  for (const n of nodes) {
    if (seenNode.has(n.id)) duplicateNodeIds.push(n.id);
    seenNode.add(n.id);
    const p = n.position;
    if (p && (!Number.isFinite(p.x) || !Number.isFinite(p.y))) {
      invalidPositions.push(n.id);
    }
  }

  const seenEdge = new Set<string>();
  const duplicateEdgeIds: string[] = [];
  const danglingEdges: IntegrityReport['danglingEdges'] = [];
  const selfLoops: string[] = [];
  for (const e of edges) {
    if (seenEdge.has(e.id)) duplicateEdgeIds.push(e.id);
    seenEdge.add(e.id);

    const missing: string[] = [];
    if (!seenNode.has(e.source)) missing.push(e.source);
    if (!seenNode.has(e.target)) missing.push(e.target);
    if (missing.length) {
      danglingEdges.push({ id: e.id, source: e.source, target: e.target, missing });
    }
    if (e.source === e.target) selfLoops.push(e.id);
  }

  return {
    ok: duplicateNodeIds.length === 0 && duplicateEdgeIds.length === 0 &&
        danglingEdges.length === 0 && selfLoops.length === 0 &&
        invalidPositions.length === 0,
    duplicateNodeIds,
    duplicateEdgeIds,
    danglingEdges,
    selfLoops,
    invalidPositions,
  };
}

export function describeIntegrity(r: IntegrityReport): string {
  if (r.ok) return '';
  const parts: string[] = [];
  if (r.duplicateNodeIds.length)
    parts.push(`${r.duplicateNodeIds.length} duplicate node id(s): ${r.duplicateNodeIds.slice(0, 5).join(', ')}`);
  if (r.duplicateEdgeIds.length)
    parts.push(`${r.duplicateEdgeIds.length} duplicate edge id(s): ${r.duplicateEdgeIds.slice(0, 5).join(', ')}`);
  if (r.danglingEdges.length)
    parts.push(`${r.danglingEdges.length} edge(s) referencing missing nodes: ` +
      r.danglingEdges.slice(0, 5).map(d => `${d.source}->${d.target}`).join(', '));
  if (r.selfLoops.length)
    parts.push(`${r.selfLoops.length} self-loop(s)`);
  if (r.invalidPositions.length)
    parts.push(`${r.invalidPositions.length} node(s) with non-finite positions: ${r.invalidPositions.slice(0, 5).join(', ')}`);
  return `Canvas graph integrity: ${parts.join(' | ')}`;
}

export function makeEdgeId(
  source: string, target: string, seen: Map<string, number>,
): string {
  const base = `e:${source}->${target}`;
  const n = seen.get(base) ?? 0;
  seen.set(base, n + 1);
  return n === 0 ? base : `${base}#${n}`;
}

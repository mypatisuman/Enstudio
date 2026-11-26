// Node/edge identity and referential safety for the Canvas boundary.
//
// Phase 3. React Flow silently misbehaves on a malformed graph rather than
// erroring: a duplicate node id renders one node and drops the other, a
// duplicate edge id renders one edge, and an edge whose source or target does
// not exist is dropped with no message. All three look like "the extraction
// missed something" from the outside.
//
// Two known ways the data can arrive malformed:
//   * two source PDFs in one project both produce local ids n1, n2, ... —
//     page scoping (Phase 1) namespaces PAGES within one document, not
//     documents within one project. That is a backend identity issue tracked
//     for Phase 5; here we make sure the Canvas surfaces it instead of
//     silently rendering half the graph.
//   * an edge that references a node filtered out by the current drawing
//     selection.
//
// Pure and React-free so it is testable without a renderer.

export interface IntegrityReport {
  ok: boolean
  duplicateNodeIds: string[]
  duplicateEdgeIds: string[]
  danglingEdges: { id: string; source: string; target: string; missing: string[] }[]
  selfLoops: string[]
  invalidPositions: string[]
}

interface MinNode { id: string; position?: { x: number; y: number } }
interface MinEdge { id: string; source: string; target: string }

/**
 * Check a React-Flow-ready node/edge set. Does NOT mutate; callers decide
 * whether to drop, warn, or both.
 */
export function checkGraphIntegrity(
  nodes: MinNode[], edges: MinEdge[],
): IntegrityReport {
  const seenNode = new Set<string>()
  const duplicateNodeIds: string[] = []
  const invalidPositions: string[] = []
  for (const n of nodes) {
    if (seenNode.has(n.id)) duplicateNodeIds.push(n.id)
    seenNode.add(n.id)
    const p = n.position
    if (p && (!Number.isFinite(p.x) || !Number.isFinite(p.y))) {
      invalidPositions.push(n.id)
    }
  }

  const seenEdge = new Set<string>()
  const duplicateEdgeIds: string[] = []
  const danglingEdges: IntegrityReport['danglingEdges'] = []
  const selfLoops: string[] = []
  for (const e of edges) {
    if (seenEdge.has(e.id)) duplicateEdgeIds.push(e.id)
    seenEdge.add(e.id)

    const missing: string[] = []
    if (!seenNode.has(e.source)) missing.push(e.source)
    if (!seenNode.has(e.target)) missing.push(e.target)
    if (missing.length) {
      danglingEdges.push({ id: e.id, source: e.source, target: e.target, missing })
    }
    if (e.source === e.target) selfLoops.push(e.id)
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
  }
}

/**
 * Human-readable summary, or '' when the graph is clean.
 * Used for a console warning — the phase brief forbids silently hiding
 * topology, so a malformed graph must say so rather than just rendering less.
 */
export function describeIntegrity(r: IntegrityReport): string {
  if (r.ok) return ''
  const parts: string[] = []
  if (r.duplicateNodeIds.length)
    parts.push(`${r.duplicateNodeIds.length} duplicate node id(s): ${r.duplicateNodeIds.slice(0, 5).join(', ')}`)
  if (r.duplicateEdgeIds.length)
    parts.push(`${r.duplicateEdgeIds.length} duplicate edge id(s): ${r.duplicateEdgeIds.slice(0, 5).join(', ')}`)
  if (r.danglingEdges.length)
    parts.push(`${r.danglingEdges.length} edge(s) referencing missing nodes: ` +
      r.danglingEdges.slice(0, 5).map(d => `${d.source}->${d.target}`).join(', '))
  if (r.selfLoops.length)
    parts.push(`${r.selfLoops.length} self-loop(s)`)
  if (r.invalidPositions.length)
    parts.push(`${r.invalidPositions.length} node(s) with non-finite positions: ${r.invalidPositions.slice(0, 5).join(', ')}`)
  return `Canvas graph integrity: ${parts.join(' | ')}`
}

/**
 * A stable, collision-proof React Flow edge id.
 *
 * Edge ids used to be the array index (`t0`, `t1`, ...), which is unique per
 * render but carries no identity: it changes whenever filtering changes, so
 * React Flow cannot correlate an edge across renders, and two different
 * connections can swap ids. Keyed on the endpoints instead, with an
 * occurrence counter for genuine parallel connections between the same pair.
 */
export function makeEdgeId(
  source: string, target: string, seen: Map<string, number>,
): string {
  const base = `e:${source}->${target}`
  const n = seen.get(base) ?? 0
  seen.set(base, n + 1)
  return n === 0 ? base : `${base}#${n}`
}

import type { GraphNode, GraphEdge, Instrument, Equipment } from '../../services/invoke/types'
import type { ValidationContext, ValidationIssue, Severity } from './types'
import { RULES } from './rules'

// Build the shared context once. This is the ONLY graph traversal — every rule
// reads these precomputed structures instead of walking nodes/edges itself.
export function buildContext(
  nodes: GraphNode[], edges: GraphEdge[], instruments: Instrument[], equipment: Equipment[],
): ValidationContext {
  const nodeById = new Map(nodes.map(n => [n.id, n]))
  const connectedIds = new Set<string>()
  for (const e of edges) {
    connectedIds.add(e.source)
    connectedIds.add(e.target)
  }
  return { nodes, edges, instruments, equipment, nodeById, connectedIds }
}

// Run every rule over the context. Not memoised here — callers run this once on
// project load / manual refresh and cache the result in state (never on render).
export function runValidation(ctx: ValidationContext): ValidationIssue[] {
  const order: Record<Severity, number> = { critical: 0, warning: 1, info: 2 }
  return RULES
    .flatMap(rule => rule.execute(ctx))
    .sort((a, b) => order[a.severity] - order[b.severity])
}

const WEIGHT: Record<Severity, number> = { critical: 3, warning: 1, info: 0.5 }

// Validation score: 100 when nothing open, dropping with the weighted count of
// OPEN issues, normalised by graph size so a big clean diagram isn't punished
// for one nit. Ignored/resolved issues do not count against the score.
export function validationScore(openIssues: ValidationIssue[], ctx: ValidationContext): number {
  const objects = ctx.nodes.length + ctx.edges.length
  if (objects === 0) return openIssues.length === 0 ? 100 : 0
  const weighted = openIssues.reduce((s, i) => s + WEIGHT[i.severity], 0)
  return Math.max(0, Math.round(100 * (1 - weighted / objects)))
}

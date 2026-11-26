import type { GraphNode, GraphEdge } from '../canvas/types';
import type { ValidationContext, ValidationIssue, Severity, Instrument, Equipment } from './types';
import { RULES } from './rules';

export function buildContext(
  nodes: GraphNode[],
  edges: GraphEdge[],
  instruments: Instrument[],
  equipment: Equipment[]
): ValidationContext {
  const nodeById = new Map(nodes.map(n => [n.id, n]));
  const connectedIds = new Set<string>();
  for (const e of edges) {
    if (e.source) connectedIds.add(e.source);
    if (e.target) connectedIds.add(e.target);
  }
  return { nodes, edges, instruments, equipment, nodeById, connectedIds };
}

export function runValidation(ctx: ValidationContext): ValidationIssue[] {
  const order: Record<Severity, number> = { critical: 0, warning: 1, info: 2 };
  return RULES
    .flatMap(rule => rule.execute(ctx))
    .sort((a, b) => order[a.severity] - order[b.severity]);
}

const WEIGHT: Record<Severity, number> = { critical: 3, warning: 1, info: 0.5 };

export function validationScore(openIssues: ValidationIssue[], ctx: ValidationContext): number {
  const objects = ctx.nodes.length + ctx.edges.length;
  if (objects === 0) return openIssues.length === 0 ? 100 : 0;
  const weighted = openIssues.reduce((s, i) => s + WEIGHT[i.severity], 0);
  return Math.max(0, Math.round(100 * (1 - weighted / Math.max(objects, 1))));
}

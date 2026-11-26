import type { GraphNode, GraphEdge, Instrument, Equipment } from '../../../services/invoke/types'
import type { ValidationIssue } from '../../validation/types'
import { getGraph } from '../../../services/graph'
import { getInstruments, getEquipment } from '../../../services/review'
import { buildContext, runValidation } from '../../validation/engine'
import { getCached, setCached } from '../../validation/cache'

// Compact, structured project context for the Copilot. This is what "do NOT
// send the raw graph" means: the LLM sees summarised counts + tag lists +
// validation/statistics, never the full node/edge arrays. The raw arrays are
// kept on the object only for LOCAL search/focus (never serialised to the LLM).
export interface ProjectContext {
  projectId: string
  projectName: string
  builtAt: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  equipment: Equipment[]
  instruments: Instrument[]
  drawings: string[]
  stats: { equipment: number; instruments: number; connections: number; drawings: number }
  issues: ValidationIssue[]
  validation: { critical: number; warning: number; info: number; total: number }
}

// Per-project cache so repeated turns in a conversation reuse the same context
// (keeps response prep well under 100ms). Invalidated on manual refresh / when
// the copilot screen re-opens a project.
const cache = new Map<string, ProjectContext>()
const summaries = new Map<string, string>()   // `${pid}:${drawing}` → drawing-summary markdown

export function invalidateProjectContext(pid: string): void { cache.delete(pid) }

export function getSummary(key: string): string | undefined { return summaries.get(key) }
export function setSummary(key: string, md: string): void { summaries.set(key, md) }

// Called after any successful edit: drop the project's cached context AND its
// drawing summaries so the next Copilot turn / summary is regenerated from
// fresh data. Validation is invalidated separately by the caller.
export function refreshProjectCaches(pid: string): void {
  cache.delete(pid)
  for (const k of summaries.keys()) if (k.startsWith(`${pid}:`)) summaries.delete(k)
}

export async function getProjectContext(projectId: string, projectName: string): Promise<ProjectContext> {
  const hit = cache.get(projectId)
  if (hit) return hit

  const [graph, instruments, equipment] = await Promise.all([
    getGraph(projectId), getInstruments(projectId), getEquipment(projectId),
  ])

  // Reuse the Validation engine/cache — never recompute validation separately.
  // If the cache is warm (pre-run after extraction) use it; otherwise compute
  // once from the SAME fetched graph and seed the cache so both features agree.
  let issues = getCached(projectId)?.issues
  if (!issues) {
    const vctx = buildContext(graph.nodes, graph.edges, instruments, equipment)
    issues = runValidation(vctx)
    setCached(projectId, { issues, ctx: vctx, ranAt: Date.now() })
  }

  const drawings = [...new Set(
    [...equipment.map(e => e.drawing), ...instruments.map(i => i.drawing)].filter(Boolean),
  )].sort()

  const ctx: ProjectContext = {
    projectId, projectName, builtAt: Date.now(),
    nodes: graph.nodes, edges: graph.edges, equipment, instruments, drawings,
    stats: {
      equipment: equipment.length,
      instruments: instruments.length,
      connections: graph.edges.length,
      drawings: drawings.length,
    },
    issues,
    validation: {
      critical: issues.filter(i => i.severity === 'critical').length,
      warning:  issues.filter(i => i.severity === 'warning').length,
      info:     issues.filter(i => i.severity === 'info').length,
      total:    issues.length,
    },
  }
  cache.set(projectId, ctx)
  return ctx
}

// Group tags by a coarse kind so the LLM prompt stays compact. `kind_detail`
// (e.g. "pump", "control_valve") is the richest signal we already extract.
function tagsByKind(items: { tag: string; kind_detail: string; type: string }[]): string {
  const groups = new Map<string, string[]>()
  for (const it of items) {
    const k = (it.kind_detail || it.type || 'other').toLowerCase()
    const arr = groups.get(k) ?? []
    if (arr.length < 30) arr.push(it.tag)   // cap per group so the block stays small
    groups.set(k, arr)
  }
  return [...groups.entries()]
    .map(([k, tags]) => `  ${k} (${tags.length}): ${tags.join(', ')}`)
    .join('\n')
}

// Serialise ONLY the compact summary for the LLM — this is the entire graph the
// model ever sees. Deterministic and small (a few KB even for large projects).
export function formatContextForPrompt(ctx: ProjectContext): string {
  const v = ctx.validation
  const topIssues = ctx.issues.slice(0, 20)
    .map(i => `  [${i.severity}] ${i.title}${i.tag ? ` (${i.tag})` : ''}`)
    .join('\n')
  return [
    `PROJECT: ${ctx.projectName}`,
    `DRAWINGS (${ctx.drawings.length}): ${ctx.drawings.join(', ') || 'n/a'}`,
    `STATISTICS: ${ctx.stats.equipment} equipment · ${ctx.stats.instruments} instruments · ${ctx.stats.connections} connections`,
    ``,
    `EQUIPMENT BY TYPE:`,
    tagsByKind(ctx.equipment) || '  none',
    ``,
    `INSTRUMENTS BY TYPE:`,
    tagsByKind(ctx.instruments) || '  none',
    ``,
    `VALIDATION: ${v.total} issues (${v.critical} critical, ${v.warning} warning, ${v.info} info)`,
    topIssues ? `TOP ISSUES:\n${topIssues}` : '',
  ].filter(Boolean).join('\n')
}

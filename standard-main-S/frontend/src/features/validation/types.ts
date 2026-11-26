import type { GraphNode, GraphEdge, Instrument, Equipment } from '../../services/invoke/types'

// Re-exported so rules.ts and other consumers import the graph types from the
// validation barrel rather than reaching into services/invoke themselves.
export type { GraphNode, GraphEdge, Instrument, Equipment }

export type Severity = 'critical' | 'warning' | 'info'
export type IssueStatus = 'open' | 'ignored' | 'resolved'

// A single validation finding. `id` is deterministic (ruleId + a stable key
// derived from the affected object) so a saved Open/Ignored/Resolved status
// re-attaches to the same issue on every re-run.
export interface ValidationIssue {
  id: string
  ruleId: string
  severity: Severity
  category: 'equipment' | 'instrument' | 'connection' | 'symbol'
  title: string
  description: string
  tag?: string          // affected object's canvas tag — enables Jump to Canvas
  drawing?: string
  suggestion?: string
}

// Everything a rule needs, fetched once and shared so no rule re-traverses the
// graph. Built by buildContext() in engine.ts from existing extraction results.
export interface ValidationContext {
  nodes: GraphNode[]
  edges: GraphEdge[]
  instruments: Instrument[]
  equipment: Equipment[]
  nodeById: Map<string, GraphNode>
  connectedIds: Set<string>   // node ids that appear on at least one edge
}

// A rule is a self-contained module. Adding a new check = add one object to the
// RULES array in rules.ts; nothing else changes.
export interface ValidationRule {
  id: string
  label: string        // shown in the Issue Type filter
  severity: Severity
  execute(ctx: ValidationContext): ValidationIssue[]
}

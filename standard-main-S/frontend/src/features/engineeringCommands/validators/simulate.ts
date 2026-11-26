import type { ProjectContext } from '../../copilot/context/projectContext'
import type { SimState, ValidationImpact } from '../types'
import type { ValidationIssue } from '../../validation/types'
import { buildContext, runValidation } from '../../validation/engine'

// Task 7 — "run validation on affected objects before executing" — is done by
// simulating the command against an in-memory clone and re-running the SAME
// Validation engine. Nothing hits the DB until the user confirms.

export function cloneState(ctx: ProjectContext): SimState {
  return {
    nodes: ctx.nodes.map(n => ({ ...n })),
    edges: ctx.edges.map(e => ({ ...e })),
    instruments: ctx.instruments.map(i => ({ ...i })),
    equipment: ctx.equipment.map(e => ({ ...e })),
  }
}

export function validate(state: SimState): ValidationIssue[] {
  return runValidation(buildContext(state.nodes, state.edges, state.instruments, state.equipment))
}

const counts = (issues: ValidationIssue[]) => ({
  critical: issues.filter(i => i.severity === 'critical').length,
  warning: issues.filter(i => i.severity === 'warning').length,
  info: issues.filter(i => i.severity === 'info').length,
})

// Diff two issue sets by their deterministic ids to report what a command would
// introduce vs. resolve.
export function impactOf(before: ValidationIssue[], after: ValidationIssue[]): ValidationImpact {
  const beforeIds = new Set(before.map(i => i.id))
  const afterIds = new Set(after.map(i => i.id))
  return {
    before: counts(before),
    after: counts(after),
    newIssues: after.filter(i => !beforeIds.has(i.id)).map(i => i.title),
    resolvedIssues: before.filter(i => !afterIds.has(i.id)).map(i => i.title),
  }
}

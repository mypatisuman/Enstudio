import type { ProjectContext } from '../../copilot/context/projectContext'
import type { CommandPreview, HistoryEntry } from '../types'
import { buildPlan, type CommandRequest } from './commands'
import { cloneState, validate, impactOf } from '../validators/simulate'
import { pushHistory } from '../history/history'
import { refreshAfterEdit } from './refresh'

// EngineeringCommandExecutor (Task 1). The pipeline is always:
//   plan → validate (simulated) → [user confirms] → execute → undo history.
// planCommand NEVER mutates; only executePreview does, and only after confirm.

export function planCommand(req: CommandRequest, ctx: ProjectContext): CommandPreview {
  try {
    const plan = buildPlan(req, ctx)
    const after = validate(plan.simulate(cloneState(ctx)))
    const validation = impactOf(ctx.issues, after)
    const warnings = [
      ...plan.warnings,
      ...validation.newIssues.map(t => `Would introduce: ${t}`),
    ]
    return {
      kind: req.kind, title: plan.title, affected: plan.affected,
      warnings, destructive: plan.destructive, validation, _apply: plan.apply,
    }
  } catch (e: unknown) {
    return {
      kind: req.kind, title: 'Command not applicable', affected: [], warnings: [],
      destructive: false,
      validation: { before: { critical: 0, warning: 0, info: 0 }, after: { critical: 0, warning: 0, info: 0 }, newIssues: [], resolvedIssues: [] },
      error: e instanceof Error ? e.message : String(e),
      _apply: async () => { throw e },
    }
  }
}

export interface ExecContext { projectId: string; user: string }

// Execute a previewed command: run the mutations, record the inverse in AI
// history, then refresh all caches (Task 5). Returns the history entry so the
// UI can offer Undo.
export async function executePreview(preview: CommandPreview, cc: ExecContext): Promise<HistoryEntry> {
  if (preview.error) throw new Error(preview.error)
  const undo = await preview._apply()
  const entry = pushHistory({ projectId: cc.projectId, title: preview.title, by: cc.user, undo })
  await refreshAfterEdit(cc.projectId)
  return entry
}

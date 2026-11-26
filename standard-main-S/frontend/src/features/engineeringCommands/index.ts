// Public surface of the Engineering Command module. The Copilot invokes ONLY
// through here (Task 9). Canvas editing never calls the LLM; this module never
// calls the LLM.
export { planCommand, executePreview, type ExecContext } from './executor/executor'
export { buildPlan, type CommandRequest } from './executor/commands'
export { listHistory, subscribeHistory, undoEntry } from './history/history'
export type { CommandPreview, HistoryEntry, CommandKind, AffectedObject, ValidationImpact } from './types'

import { getGraph } from '../../services/graph'
import { getInstruments, getEquipment } from '../../services/review'
import { buildContext, runValidation } from './engine'
import { setCached, type ValidationResult } from './cache'

// Fetch the current extraction results, run every rule once, and cache the
// outcome. Shared by the auto-run-after-extraction hook and the Validation
// screen's manual refresh so there is a single validation code path.
export async function runAndCacheValidation(pid: string): Promise<ValidationResult> {
  const [graph, instruments, equipment] = await Promise.all([
    getGraph(pid), getInstruments(pid), getEquipment(pid),
  ])
  const ctx = buildContext(graph.nodes, graph.edges, instruments, equipment)
  const result: ValidationResult = { issues: runValidation(ctx), ctx, ranAt: Date.now() }
  setCached(pid, result)
  return result
}

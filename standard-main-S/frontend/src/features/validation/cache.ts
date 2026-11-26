import type { ValidationIssue, ValidationContext } from './types'

// Process-wide cache of the last validation run per project. Lets validation be
// a pipeline step: it runs once when extraction finishes (see useAutoValidation)
// and the Validation screen reads the cached result instantly instead of
// recomputing on every open. Lives outside React so a run triggered while the
// screen is unmounted still lands here.
export interface ValidationResult {
  issues: ValidationIssue[]
  ctx: ValidationContext
  ranAt: number
}

const cache = new Map<string, ValidationResult>()
const subs = new Set<(pid: string) => void>()

export function getCached(pid: string): ValidationResult | undefined {
  return cache.get(pid)
}

export function setCached(pid: string, result: ValidationResult): void {
  cache.set(pid, result)
  subs.forEach(fn => fn(pid))
}

// Drop a project's cached run (e.g. after a mutation) so it recomputes next time.
export function invalidateValidation(pid: string): void {
  cache.delete(pid)
  subs.forEach(fn => fn(pid))
}

// Subscribe to cache writes (e.g. the screen refreshing when auto-validation
// finishes after an extraction). Returns an unsubscribe fn.
export function subscribeValidation(fn: (pid: string) => void): () => void {
  subs.add(fn)
  return () => { subs.delete(fn) }
}

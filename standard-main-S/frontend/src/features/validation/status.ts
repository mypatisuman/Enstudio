import type { IssueStatus } from './types'

// Issue status is a review overlay (Open is the default, so we only persist the
// non-default Ignored/Resolved). Kept in localStorage keyed by project — the
// underlying extraction is untouched, so this needs no DB/schema change.
const KEY = (pid: string) => `enstudio:validation-status:v1:${pid}`

export type StatusMap = Record<string, IssueStatus>

export function loadStatuses(pid: string): StatusMap {
  try {
    const raw = localStorage.getItem(KEY(pid))
    return raw ? (JSON.parse(raw) as StatusMap) : {}
  } catch {
    return {}
  }
}

export function saveStatuses(pid: string, map: StatusMap): void {
  try {
    // Drop entries that fell back to Open so the store stays small.
    const trimmed: StatusMap = {}
    for (const [id, st] of Object.entries(map)) if (st !== 'open') trimmed[id] = st
    localStorage.setItem(KEY(pid), JSON.stringify(trimmed))
  } catch {
    /* storage full / disabled — status just won't persist */
  }
}

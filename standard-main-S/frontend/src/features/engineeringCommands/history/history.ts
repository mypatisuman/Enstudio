import type { HistoryEntry, UndoFn } from '../types'
import { refreshAfterEdit } from '../executor/refresh'

// AI Action History (Task 8). Session-scoped, per project. Each entry keeps its
// inverse closure so a single action can be undone — mirroring the Canvas's
// command-stack pattern (the Canvas's own stack is React-state-bound and
// unreachable from the Copilot screen, so AI edits keep their own history).
interface Entry extends HistoryEntry { projectId: string }

const entries: Entry[] = []
const subs = new Set<() => void>()
let seq = 0

// Snapshot cache keyed by project, versioned by `notify`, so listHistory returns
// a STABLE array reference between changes — required by useSyncExternalStore
// (a fresh array every call would loop forever).
let version = 0
const snapshots = new Map<string, { v: number; list: HistoryEntry[] }>()

const notify = () => { version++; subs.forEach(fn => fn()) }

export function subscribeHistory(fn: () => void): () => void {
  subs.add(fn)
  return () => { subs.delete(fn) }
}

export function listHistory(projectId: string): HistoryEntry[] {
  const cached = snapshots.get(projectId)
  if (cached && cached.v === version) return cached.list
  const list = entries.filter(e => e.projectId === projectId)
  snapshots.set(projectId, { v: version, list })
  return list
}

export function pushHistory(e: { projectId: string; title: string; by: string; undo: UndoFn }): HistoryEntry {
  const entry: Entry = { id: `h${Date.now()}_${seq++}`, at: Date.now(), undone: false, ...e }
  entries.unshift(entry)
  notify()
  return entry
}

export async function undoEntry(id: string): Promise<void> {
  const entry = entries.find(e => e.id === id)
  if (!entry || entry.undone) return
  await entry.undo()
  entry.undone = true
  notify()
  await refreshAfterEdit(entry.projectId)
}

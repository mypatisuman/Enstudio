// Typed invoke wrappers for src-tauri/src/commands/activity.rs — persists the
// extraction activity feed to the DB (30-day retention) so it survives app
// restarts, unlike the in-memory-only state it replaced.

import { invoke } from '@tauri-apps/api/core'
import type { LogEntry } from '../../state/extraction/types'

export interface PersistedActivityEntry extends LogEntry {
  pid: string
}

export function saveActivityEntry(projectId: string, entry: LogEntry): Promise<void> {
  return invoke('save_activity_entry', {
    entry: {
      projectId,
      stage:      entry.stage,
      label:      entry.label,
      detail:     entry.detail,
      status:     entry.status,
      startedAt:  entry.startedAt,
      durationMs: entry.durationMs ?? null,
      indent:     !!entry.indent,
    },
  })
}

export function getActivityLog(): Promise<PersistedActivityEntry[]> {
  return invoke('get_activity_log')
}

export function clearActivityLog(projectId: string): Promise<void> {
  return invoke('clear_activity_log', { projectId })
}

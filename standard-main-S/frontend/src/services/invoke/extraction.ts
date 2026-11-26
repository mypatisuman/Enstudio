// Typed invoke wrappers for src-tauri/src/commands/extraction.rs.

import { invoke } from '@tauri-apps/api/core'

export function runExtraction(projectId: string, sourceId: number, llmOnly?: boolean): Promise<unknown> {
  return invoke('run_extraction', { projectId, sourceId, llmOnly })
}

export function cancelExtraction(projectId: string): Promise<unknown> {
  return invoke('cancel_extraction', { projectId })
}

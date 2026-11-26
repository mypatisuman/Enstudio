import { emit } from '@tauri-apps/api/event'
import { refreshProjectCaches } from '../../copilot/context/projectContext'
import { invalidateValidation } from '../../validation/cache'
import { runAndCacheValidation } from '../../validation/run'

// Task 5 — after any successful edit (or its undo): invalidate the Copilot
// context + drawing summaries, re-run Validation to warm its cache (which also
// notifies the Validation screen's subscribers), and tell the rest of the app
// the project changed. No manual refresh anywhere.
export async function refreshAfterEdit(projectId: string): Promise<void> {
  refreshProjectCaches(projectId)
  invalidateValidation(projectId)
  await runAndCacheValidation(projectId).catch(() => { /* best-effort re-validate */ })
  emit('project-updated').catch(() => {})
}

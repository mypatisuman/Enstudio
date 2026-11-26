import type { CopilotMessage } from '../types'
import type { ProjectContext } from '../context/projectContext'
import { formatContextForPrompt } from '../context/projectContext'

export interface PromptParts {
  system: string
  apiMessages: { role: string; content: string }[]
}

// Reusable prompt builder (Task 10): keep the four layers separate instead of
// concatenating strings at call sites. The compact project context is attached
// to the FIRST user turn as a labelled block; conversation history is passed
// through as-is; the latest request is the final user turn.
const HISTORY_LIMIT = 10   // last N turns — keeps the request small and cheap

export function buildCopilotMessages(
  system: string,
  ctx: ProjectContext,
  history: CopilotMessage[],
  request: string,
): PromptParts {
  const recent = history.slice(-HISTORY_LIMIT)
  const contextBlock = `PROJECT CONTEXT:\n${formatContextForPrompt(ctx)}`

  const apiMessages: { role: string; content: string }[] = []
  // Seed the context once as a user/assistant priming pair so it counts as
  // history the model already "knows" rather than being re-sent every turn.
  apiMessages.push({ role: 'user', content: contextBlock })
  apiMessages.push({ role: 'assistant', content: 'Understood. I have the current project context and will answer only from it.' })

  for (const m of recent) {
    apiMessages.push({ role: m.role, content: m.content })
  }
  apiMessages.push({ role: 'user', content: request })

  return { system, apiMessages }
}

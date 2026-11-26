// Public types for the Engineering Copilot. Kept in one module so the single
// public service (copilotService) and the panel share one contract.

import type { CommandPreview } from '../../engineeringCommands/types'

export type CopilotRole = 'user' | 'assistant'

// One clickable object in a result list — clicking focuses it on the Canvas
// through the existing FocusBus (tag → node).
export interface CopilotResult {
  tag: string
  title: string          // "Pump P-101"
  detail: string         // "pump · Drawing 2 · 92%"
}

export interface CopilotMessage {
  id: string
  role: CopilotRole
  content: string              // markdown
  results?: CopilotResult[]
  pending?: CommandPreview     // an editing command awaiting Confirm/Cancel
  undoId?: string              // AI-history id once a command has executed (enables Undo)
  streaming?: boolean
  error?: boolean
  navigatedTo?: string         // tag the assistant focused on the Canvas
}

export type CopilotSend = (text: string) => void

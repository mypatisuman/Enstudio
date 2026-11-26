// Typed invoke wrappers for src-tauri/src/commands/describe.rs.

import { invoke } from '@tauri-apps/api/core'
import type { DescribeSession, DescribeMessageRow } from './types'

export function listDescribeSessions(projectId: string): Promise<DescribeSession[]> {
  return invoke('list_describe_sessions', { projectId })
}

export function createDescribeSession(projectId: string): Promise<{ id: number }> {
  return invoke('create_describe_session', { projectId })
}

export function getDescribeMessages(sessionId: number): Promise<DescribeMessageRow[]> {
  return invoke('get_describe_messages', { sessionId })
}

export interface SaveDescribeMessageArgs {
  // Callers occasionally have a not-yet-created session id (sessionId
  // creation failed earlier in the same try/catch) — the pre-existing
  // behavior sends the request anyway and lets it fail, caught by the
  // caller's own .catch(). Typed as nullable to match reality rather than
  // changing that behavior.
  sessionId: number | null
  projectId: string
  role: string
  display: string
  apiContent: string
  nodesAdded: number
  edgesAdded: number
  nodesUpdated: number
  pendingDeletes: string | null
  isError: boolean
}

export function saveDescribeMessage(args: SaveDescribeMessageArgs): Promise<{ id: number }> {
  return invoke('save_describe_message', { ...args })
}

export function resolveDescribeDelete(messageId: number, resolution: string, nodesDeleted: number): Promise<void> {
  return invoke('resolve_describe_delete', { messageId, resolution, nodesDeleted })
}

// ── Agentic Describe ─────────────────────────────────────────────────────────
// Routes one message to the backend's eight Describe specialists (query,
// authoring, update, deletion, validation, solution, greenfield, brownfield)
// instead of the client-side LLM turn in DescribeScreen. The agents own their
// tools and write to the graph themselves, so the caller refreshes the graph
// afterwards rather than applying ops locally.

export interface DescribeAgentOp {
  tool?: string
  result?: string
  [k: string]: unknown
}

export interface DescribeAgentResult {
  /** Envelope status from run_describe.py: 'ok' | 'pending_delete'. */
  status: string
  /** The specialist's own outcome, e.g. 'no_pending'. */
  agent_status?: string | null
  /** Which specialist handled the turn. */
  agent?: string | null
  reply?: string | null
  title?: string | null
  solution_design?: unknown
  ops?: DescribeAgentOp[]
  /** Present when the Deletion agent paused for confirmation. */
  pending_delete?: { tags?: string[]; resolved?: string; [k: string]: unknown }
}

export function describeAgentTurn(
  projectId: string, message: string, sessionId?: string,
): Promise<DescribeAgentResult> {
  return invoke('describe_agent_turn', { projectId, message, sessionId })
}

export function describeAgentResolve(
  projectId: string, confirmed: boolean, sessionId?: string,
): Promise<DescribeAgentResult> {
  return invoke('describe_agent_resolve', { projectId, sessionId, confirmed })
}

export function renameDescribeSession(sessionId: number, title: string): Promise<void> {
  return invoke('rename_describe_session', { sessionId, title })
}

export function deleteDescribeSession(sessionId: number): Promise<void> {
  return invoke('delete_describe_session', { sessionId })
}

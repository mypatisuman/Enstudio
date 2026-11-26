export interface GraphNode { id: string; label: string; kind: string; area: string; drawing: string; x: number; y: number }
export interface GraphEdge { source: string; target: string; kind: string }
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[] }

export interface ClaudeNode { tag: string; kind: string; area: string; description: string }
export interface ClaudeEdge { from_tag: string; to_tag: string; kind: string }
export interface ClaudeUpdate { tag: string; new_tag?: string; kind?: string; area?: string; description?: string; move_near?: string }
export interface ClaudeJunction { id: string }
export interface ClaudeResponse {
  add_nodes?: ClaudeNode[]
  add_junctions?: ClaudeJunction[]
  add_edges?: ClaudeEdge[]
  update_nodes?: ClaudeUpdate[]
  delete_nodes?: string[]
  title?: string
  reply?: string
}

export interface ChatEntry {
  dbId?: number             // row id in describe_messages, once persisted
  role: 'user' | 'assistant'
  display: string           // human-readable text shown in chat
  apiContent: string        // content sent to / received from API
  nodesAdded?: number
  edgesAdded?: number
  nodesUpdated?: number
  isError?: boolean
  pendingDeletes?: string[]         // tags awaiting delete confirmation
  deleteResolution?: 'confirmed' | 'cancelled'
  nodesDeleted?: number
  // Assistant-style answers (search / explain / summary / validation), merged in
  // from the former Copilot screen: markdown body + clickable results that focus
  // a node on the Canvas.
  answerMarkdown?: boolean
  results?: { tag: string; title: string; detail: string }[]
  // Files attached to this turn (cosmetic — shown as chips on the bubble).
  // Not persisted as binary and not resent to the LLM on later turns; only the
  // note in `apiContent`/`display` (e.g. "[Attached image: x.png]") survives
  // a reload, so history never balloons with base64.
  attachments?: { name: string; kind: string }[]
}

export interface DescribeSession {
  id: number
  title: string
  updated_at: string
  message_count: number
}

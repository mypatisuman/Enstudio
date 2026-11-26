import type { GraphNode, GraphEdge, Instrument, Equipment } from '../../../services/invoke/types'

export type CommandKind =
  | 'rename' | 'rename-bulk'
  | 'move'
  | 'delete-node' | 'delete-edge' | 'disconnect' | 'delete-unused'
  | 'create-connection' | 'connect-instrument'
  | 'duplicate'
  | 'align' | 'distribute' | 'auto-layout'

// A cloneable snapshot the validators mutate in-memory to preview a command's
// effect BEFORE anything touches the database.
export interface SimState {
  nodes: GraphNode[]
  edges: GraphEdge[]
  instruments: Instrument[]
  equipment: Equipment[]
}

export interface AffectedObject { tag: string; change: string }

// Validation delta a command would cause, computed by simulating it and
// re-running the Validation engine on the result.
export interface ValidationImpact {
  before: { critical: number; warning: number; info: number }
  after: { critical: number; warning: number; info: number }
  newIssues: string[]
  resolvedIssues: string[]
}

export type UndoFn = () => Promise<void>

// Internal plan produced by a command builder — the executor turns it into a
// CommandPreview and, on confirm, runs `apply`.
export interface Plan {
  title: string
  affected: AffectedObject[]
  warnings: string[]
  destructive: boolean
  simulate: (s: SimState) => SimState   // pure — for the validation preview
  apply: () => Promise<UndoFn>          // performs the real mutations, returns its inverse
}

// What the Preview panel renders and what confirm() executes.
export interface CommandPreview {
  kind: CommandKind
  title: string
  affected: AffectedObject[]
  warnings: string[]
  destructive: boolean
  validation: ValidationImpact
  error?: string
  _apply: () => Promise<UndoFn>         // opaque; only the executor calls it
}

export interface HistoryEntry {
  id: string
  title: string
  at: number
  by: string
  undo: UndoFn
  undone: boolean
}

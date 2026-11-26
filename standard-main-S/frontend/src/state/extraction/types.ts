export type EntryStatus = 'running' | 'complete' | 'error' | 'warn' | 'info'

export interface LogEntry {
  stage:      string
  label:      string
  detail:     string
  status:     EntryStatus
  startedAt:  number        // ms — when the entry first appeared
  durationMs?: number       // ms — set when a 'running' entry transitions to done/error
  indent?:    boolean       // render nested under a parent row (e.g. detectors under Extracting)
}

// One project's extraction state — the map below is keyed by project_id, so
// multiple projects can extract concurrently without stepping on each other.
export interface PerProjectState {
  log:          LogEntry[]
  isExtracting: boolean
  extractDone:  boolean
  extractError: boolean
  extractRow:   number | null
  rowResult:    Record<number, string>
  doneFired:    boolean
  errorFired:   boolean
}

export function emptyState(): PerProjectState {
  return {
    log: [], isExtracting: false, extractDone: false, extractError: false,
    extractRow: null, rowResult: {}, doneFired: false, errorFired: false,
  }
}

export interface ExtractionCtxValue {
  byProject: Record<string, PerProjectState>
  start:  (projectId: string, sourceId: number, llmOnly?: boolean) => Promise<void>
  cancel: (projectId: string) => Promise<void>
  reset:  (projectId: string) => void
  // Pushes one entry into the Latest Activity feed (persisted to the DB +
  // reflected live in byProject) — for activity that doesn't come from the
  // extraction-progress event stream, e.g. a Describe chat turn.
  logActivity: (projectId: string, entry: LogEntry) => void
}

// Per-project view returned by useExtraction(projectId) — same flat shape
// IngestScreen already expects, just bound to one project's slice + actions.
export interface ExtractionCtx extends PerProjectState {
  projectId: string
  start:  (sourceId: number, llmOnly?: boolean) => Promise<void>
  cancel: () => Promise<void>
  reset:  () => void
}

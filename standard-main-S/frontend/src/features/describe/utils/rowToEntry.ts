import type { ChatEntry } from '../types'

// Converts a describe_messages DB row into a ChatEntry for hydration.
export function rowToEntry(row: any): ChatEntry {
  return {
    dbId:             row.id,
    role:             row.role,
    display:          row.display,
    apiContent:       row.api_content,
    nodesAdded:       row.nodes_added,
    edgesAdded:       row.edges_added,
    nodesUpdated:     row.nodes_updated,
    isError:          !!row.is_error,
    pendingDeletes:   row.pending_deletes ? JSON.parse(row.pending_deletes) : undefined,
    deleteResolution: row.delete_resolution ?? undefined,
    nodesDeleted:     row.nodes_deleted,
  }
}

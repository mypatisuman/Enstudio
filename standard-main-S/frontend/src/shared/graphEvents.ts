// Cross-screen signals for graph edits and plant-hierarchy filtering.
//
// The Describe agents write to the database from a spawned backend process, so
// nothing inside React knows the graph changed. The Canvas and the hierarchy
// panel listen for GRAPH_CHANGED and reload; the hierarchy panel publishes a
// filter the Canvas applies by dimming nodes outside the selected system.

export const GRAPH_CHANGED = 'enstudio:graph-changed'
export const HIERARCHY_FILTER = 'enstudio:hierarchy-filter'

export interface GraphChangedDetail { projectId: string }
export interface HierarchyFilterDetail {
  projectId: string
  /** Node ids to keep fully visible; null clears the filter. */
  nodeIds: string[] | null
  label?: string
}

export function emitGraphChanged(projectId: string): void {
  window.dispatchEvent(new CustomEvent<GraphChangedDetail>(GRAPH_CHANGED, { detail: { projectId } }))
}

export function onGraphChanged(handler: (d: GraphChangedDetail) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<GraphChangedDetail>).detail)
  window.addEventListener(GRAPH_CHANGED, listener)
  return () => window.removeEventListener(GRAPH_CHANGED, listener)
}

export function emitHierarchyFilter(detail: HierarchyFilterDetail): void {
  window.dispatchEvent(new CustomEvent<HierarchyFilterDetail>(HIERARCHY_FILTER, { detail }))
}

export function onHierarchyFilter(handler: (d: HierarchyFilterDetail) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<HierarchyFilterDetail>).detail)
  window.addEventListener(HIERARCHY_FILTER, listener)
  return () => window.removeEventListener(HIERARCHY_FILTER, listener)
}

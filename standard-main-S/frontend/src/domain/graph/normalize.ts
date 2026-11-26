// Graph normalization — moved out of CanvasScreen.tsx unchanged.
//
// get_graph always sends `type` as a string ("" when nothing was detected),
// but call sites use `n.type ?? n.kind` — `??` doesn't fall through on "",
// so an empty type silently wins over kind (e.g. junctions rendered as a
// generic box instead of the dot). Normalize "" to undefined once, right
// where the graph lands.

export interface NormalizableNode {
  type?: string
}

export function normalizeGraphNodes<T extends NormalizableNode>(nodes: T[]): T[] {
  nodes.forEach(n => { if (n.type === '') n.type = undefined })
  return nodes
}

import type { ISANodeData } from '../../components/canvas/ISANodes'

export interface GraphNode {
  id: string; label: string; kind: string; kind_detail: string
  x: number; y: number; area: string; drawing: string; equipment_ref: string
  category?: string
  type?: string   // raw detector type, e.g. "Inlet"/"Outlet" — authoritative for connector direction
  source_id?: number        // sources.id of the document this came from (Phase 5)
  page?: number             // 1-based source page, unique only within source_id
  page_w?: number           // raster size the normalised x/y were measured
  page_h?: number           // against (Phase 3) — drives per-drawing cell aspect
}

/** How a connection was established. See the Phase 2 geometry-first guard. */
export type EdgeProvenance = 'geometry' | 'llm'

export interface GraphEdge {
  source: string; target: string; kind: string; waypoints?: [number, number][]
  bend_x?: number; bend_y?: number   // user-dragged pipe corner (0-1 sheet coords)
  source_id?: number        // document this edge came from (Phase 5)
  provenance?: EdgeProvenance
  audited?: boolean                  // false = LLM B never audited it
}
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[] }

export type CData = ISANodeData

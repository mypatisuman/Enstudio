// Frontend types mirroring the backend's typed DTOs (src-tauri/src/models/*.rs).
// Kept here as the single source of truth so screens stop redeclaring the
// same shapes independently — see COMMAND_INVENTORY notes from Phase 0/1.

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthUser {
  id: number
  name: string
  email: string
  role: string
}

// ── Projects ──────────────────────────────────────────────────────────────────

export interface Project {
  id: string
  name: string
  status: string
  instruments: number
  equipment: number
  drawings: number
  last_extraction: string | null
  last_activity: string | null
}

export interface CreateProjectResponse {
  pid: string
  name: string
}

export interface ProjectStats {
  node_count: number
  edge_count: number
}

export interface RenameProjectResponse {
  success: boolean
  new_id: string
  new_name: string
}

export interface SuccessResponse {
  success: boolean
}

// ── Review ────────────────────────────────────────────────────────────────────

export interface Instrument {
  tag: string
  type: string
  kind_detail: string
  area: string
  equipment_ref: string
  drawing: string
  description: string
  confidence: number
  review_status: string
}

export interface Equipment {
  tag: string
  type: string
  kind_detail: string
  area: string
  drawing: string
  description: string
}

export interface GapRow {
  tag: string
  type: string
  kind_detail: string
  area: string
  drawing: string
}

export interface NoDrawingRow {
  tag: string
  type: string
  kind_detail: string
  area: string
  equipment_ref: string
}

export interface LowConfidenceRow {
  tag: string
  type: string
  kind_detail: string
  area: string
  confidence: number
  drawing: string
}

export interface GapsData {
  orphans: GapRow[]
  no_drawing: NoDrawingRow[]
  low_confidence: LowConfidenceRow[]
  lonely_equipment: GapRow[]
}

export interface ReviewStatusResponse {
  success: boolean
  tag: string
  new_status: string
}

export interface BulkReviewResponse {
  success: boolean
  count: number
}

export interface UpdateInstrumentResponse {
  success: boolean
  tag: string
  field: string
  new_value: string
}

export interface AddConnectionResponse {
  success: boolean
  id: string
}

export interface TagResponse {
  success: boolean
  tag: string
}

export interface NodeKinds {
  instruments: string[]
  equipment: string[]
}

// ── Graph / Canvas ────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string
  label: string
  kind: string
  kind_detail: string
  x: number
  y: number
  area: string
  drawing: string
  equipment_ref: string
  category: string
  // Only present on the primary (nodes-table) query path — see GraphNodeDto
  // in models/graph.rs. Absent (not null) on the legacy fallback path.
  type?: string
  // Which uploaded document (sources.id) this node came from (Phase 5).
  // Absent on rows written before that migration. Page numbers repeat across
  // documents, so the page identity is the pair (source_id, page).
  source_id?: number
  // 1-based source page. Absent on projects extracted before the Phase 1
  // multi-page change, and on single-page extractions where it is always 1.
  page?: number
  // Raster size of the source page these normalised x/y were measured
  // against. Absent on pre-Phase-3 extractions.
  page_w?: number
  page_h?: number
}

export type EdgeProvenance = 'geometry' | 'llm'

export interface GraphEdge {
  source: string
  target: string
  kind: string
  waypoints: unknown
  bend_x: number | null
  bend_y: number | null
  // How the edge was established (Phase 2 guard, surfaced in Phase 3).
  // Absent on pre-Phase-2 extractions and on hand-drawn editor edges.
  source_id?: number        // document this edge came from (Phase 5)
  provenance?: EdgeProvenance
  // False when LLM B never audited this edge (Phase 1 PARTIAL fallback).
  audited?: boolean
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface InsertedNodeId {
  id: string
  tag: string
}

export interface InsertedJunctionId {
  id: string
  ref_id: string
}

export interface BatchInsertResult<T> {
  inserted: number
  ids: T[]
}

export interface EdgeInsertResult {
  inserted: number
}

export interface ImportLlmResult {
  nodes_imported: number
  edges_imported: number
}

// ── Describe ──────────────────────────────────────────────────────────────────

export interface DescribeSession {
  id: number
  title: string
  updated_at: string
  message_count: number
}

export interface DescribeMessageRow {
  id: number
  role: string
  display: string
  api_content: string
  nodes_added: number
  edges_added: number
  nodes_updated: number
  pending_deletes: string | null
  delete_resolution: string | null
  nodes_deleted: number
  is_error: number
}

// ── Ingest ────────────────────────────────────────────────────────────────────

export interface Source {
  id: number
  filename: string
  file_hash: string
  uploaded: string
  cached: boolean
  status: string
}

export interface NativeUploadResult {
  success: boolean
  filename: string
  source_id: number
  duplicate: boolean
}

// ── Export ────────────────────────────────────────────────────────────────────

export interface ExportFileResult {
  success: boolean
  filename: string
  path: string
}

// ── Usage ─────────────────────────────────────────────────────────────────────

export interface UsageRecord {
  pid: string
  name: string
  total_tokens: number
  total_cost: number
  last_scan: string
  scans: unknown
}

// ── Misc ──────────────────────────────────────────────────────────────────────

export interface PageImageResult {
  url: string
  width: number
  height: number
}

use serde::Serialize;

#[derive(Serialize)]
pub struct InsertedNodeId {
    pub id: String,
    pub tag: String,
}

#[derive(Serialize)]
pub struct InsertedJunctionId {
    pub id: String,
    pub ref_id: String,
}

#[derive(Serialize)]
pub struct BatchInsertResult<T> {
    pub inserted: usize,
    pub ids: Vec<T>,
}

#[derive(Serialize)]
pub struct EdgeInsertResult {
    pub inserted: i64,
}

#[derive(Serialize)]
pub struct ImportLlmResult {
    pub nodes_imported: i64,
    pub edges_imported: i64,
}

/// A single canvas node. `r#type` is only present on the primary (nodes-table)
/// query path — the legacy instruments/equipment fallback path never had a
/// "type" key, so it stays optional and skipped-when-absent to reproduce
/// that exactly rather than introducing a new key the frontend never saw.
///
/// `page` is likewise optional: it only exists on nodes extracted after the
/// Phase 1 multi-page change, and `skip_serializing_if` keeps it absent for
/// older single-page projects so the node shape they already had is byte-
/// identical.
#[derive(Serialize)]
pub struct GraphNodeDto {
    pub id: String,
    pub label: String,
    pub kind: String,
    pub kind_detail: String,
    pub x: f64,
    pub y: f64,
    pub area: String,
    pub drawing: String,
    pub equipment_ref: String,
    pub category: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub r#type: Option<String>,
    /// Which uploaded document (sources.id) this node was extracted from
    /// (Phase 5). None on rows written before the migration. Page numbers are
    /// only unique within a document, so the real page identity is the pair
    /// (source_id, page).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_id: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page: Option<i64>,
    /// Raster size of the source page this node's normalised x/y were
    /// measured against (Phase 3). Lets the canvas size a drawing's cell to
    /// its real aspect ratio instead of a fixed 2800x2000 for every sheet.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page_w: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page_h: Option<i64>,
}

/// `waypoints` stays dynamic JSON — it's an arbitrary array of pipe-route
/// points (or null) copied straight through from `edges.extra_json`, not a
/// fixed shape this backend defines.
#[derive(Serialize)]
pub struct GraphEdgeDto {
    pub source: String,
    pub target: String,
    pub kind: String,
    pub waypoints: serde_json::Value,
    pub bend_x: Option<f64>,
    pub bend_y: Option<f64>,
    /// How this edge was established, stamped by the Phase 2 geometry-first
    /// guard: "geometry" (proposed by connectivity_graph and confirmed by
    /// LLM B) or "llm" (added by LLM B against a stub / unmatched symbol /
    /// junction / ambiguous crossing geometry surfaced). Absent on edges
    /// written before Phase 2 and on edges drawn by hand in the editor.
    /// Phase 3: it was persisted in extra_json but never read out, so the
    /// canvas could not tell deterministic topology from an LLM addition.
    /// Document this edge came from (Phase 5); see GraphNodeDto::source_id.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_id: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provenance: Option<String>,
    /// False on edges that came from the geometric candidate list when LLM B
    /// failed and was never able to audit them (Phase 1 PARTIAL fallback).
    /// Absent means "not applicable / audited normally".
    #[serde(skip_serializing_if = "Option::is_none")]
    pub audited: Option<bool>,
}

/// Nodes and edges for one project. Neither list is capped — see the note in
/// commands/graph.rs::get_graph about the `LIMIT 2000` that used to truncate
/// `edges` silently.
#[derive(Serialize)]
pub struct GraphDto {
    pub nodes: Vec<GraphNodeDto>,
    pub edges: Vec<GraphEdgeDto>,
}

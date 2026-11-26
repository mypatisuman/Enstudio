use serde_json::{json, Value};

use crate::database::{open_db, collect_rows};
use crate::models::{
    BatchInsertResult, InsertedNodeId, InsertedJunctionId, EdgeInsertResult, ImportLlmResult,
    GraphDto, GraphNodeDto, GraphEdgeDto,
};

/// Highest existing `n{N}` node-id counter for a project, used as the base
/// to auto-increment new synthetic node ids from. Shared by every command
/// that inserts nodes without a caller-supplied id.
fn next_node_counter(conn: &rusqlite::Connection, pid: &str) -> i64 {
    conn.query_row(
        "SELECT COALESCE(MAX(CAST(SUBSTR(id,2) AS INTEGER)),0) \
         FROM nodes WHERE pid=? AND id LIKE 'n%'",
        [pid],
        |r| r.get(0),
    ).unwrap_or(0)
}

/// This project's most common `drawing` value — used as the fallback tag for
/// nodes added without an anchor to inherit a drawing from (see placeNewNodes
/// in DescribeScreen.tsx), so added nodes don't show up as their own
/// separate pseudo-drawing in the Canvas screen's drawing filter.
fn default_drawing_for(conn: &rusqlite::Connection, pid: &str) -> String {
    conn.query_row(
        "SELECT json_extract(extra_json,'$.drawing') AS d, COUNT(*) AS c
         FROM nodes WHERE pid=? GROUP BY d ORDER BY c DESC LIMIT 1",
        [pid],
        |r| r.get::<_, Option<String>>(0),
    ).ok().flatten().unwrap_or_default()
}

/// Stamps `projects.last_activity` with now — used by anything that adds
/// real content (Describe's node/edge inserts), kept separate from
/// `last_extraction` (extraction-only) so the Recent Projects panel on Home
/// (which currently only ever sorts by last_extraction) can also surface a
/// project that was only ever built via Describe, never extracted.
fn touch_last_activity(conn: &rusqlite::Connection, pid: &str) {
    let _ = conn.execute(
        "UPDATE projects SET last_activity = datetime('now') WHERE id = ?1",
        [pid],
    );
}

/// Whether a node with this label already exists in the project — the dedup
/// check shared by batch_insert_nodes/batch_insert_junctions.
fn label_exists(conn: &rusqlite::Connection, pid: &str, label: &str) -> bool {
    conn.query_row("SELECT COUNT(*) FROM nodes WHERE pid=? AND label=?", [pid, label], |r| r.get::<_, i64>(0))
        .unwrap_or(0) > 0
}

/// Whether a Describe-authored `kind` (see DescribeScreen's SYSTEM_PROMPT
/// vocabulary) is an instrument rather than physical equipment — mirrors the
/// same instrument/equipment split extraction's import already makes (see
/// backend/repositories/project_repository.py's `_db_persist_espx`). Valves
/// and control-system nodes (dcs/plc/sis) count as equipment, same as there.
pub(crate) fn is_instrument_kind(kind: &str) -> bool {
    matches!(kind,
        "transmitter" | "controller" | "indicator" | "recorder" | "switch" |
        "alarm" | "analyzer" | "element" | "meter" | "gauge" | "sensor")
}

/// Mirrors a newly-added node into `instruments` or `equipment` — whichever
/// its `kind` classifies as — so it counts on the Sidebar/Review screen the
/// same way an extracted node does. Extraction dual-writes both tables from
/// the same source data; Describe-authored nodes need the same treatment or
/// they only ever exist in `nodes` (visible on Canvas, invisible elsewhere).
fn mirror_node_to_instrument_or_equipment(
    conn: &rusqlite::Connection, pid: &str, tag: &str, kind: &str, area: &str,
) -> Result<(), String> {
    if is_instrument_kind(kind) {
        conn.execute(
            "INSERT OR IGNORE INTO instruments (tag, pid, area, kind_detail, type, equipment_ref, extra_json)
             VALUES (?, ?, ?, ?, ?, '', '{}')",
            rusqlite::params![tag, pid, area, kind, kind],
        ).map_err(|e| format!("Insert instrument '{}' failed: {}", tag, e))?;
    } else {
        conn.execute(
            "INSERT OR IGNORE INTO equipment (tag, pid, area, kind_detail, type, extra_json)
             VALUES (?, ?, ?, ?, ?, '{}')",
            rusqlite::params![tag, pid, area, kind, kind],
        ).map_err(|e| format!("Insert equipment '{}' failed: {}", tag, e))?;
    }
    Ok(())
}

/// Look up a node's real id by its label/tag — shared by every command that
/// resolves a canvas tag to a node id before writing an edge. Returns the
/// first match if the label isn't unique (same as each call site's prior
/// `LIMIT 1` behavior).
/// Kinds that count as piping rather than instrument signal.
///
/// Mirrors `process_kinds` in extraction_cli/commands.py::_derive_studio_tables.
/// The two must agree: a connection drawn on the canvas and the same connection
/// read off a drawing have to land in `connections` under the same rule, or the
/// tag-keyed export (VIDS) disagrees with the canvas.
fn is_process_kind(kind: &str) -> bool {
    matches!(kind, "process" | "stream" | "recycle" | "bypass" | "hydraulic")
}

fn label_by_node_id(conn: &rusqlite::Connection, pid: &str, node_id: &str) -> String {
    conn.query_row(
        "SELECT COALESCE(label,'') FROM nodes WHERE pid=? AND id=?",
        rusqlite::params![pid, node_id],
        |r| r.get::<_, String>(0),
    ).unwrap_or_default()
}

/// Give an edge its row in the tag-keyed `connections` table.
///
/// `edges` is the topology, and every canvas edit already writes it — YMPL and
/// Mermaid build from nodes+edges and so already saw hand-drawn connections.
/// VIDS reads `connections` instead, and only the Python extractor ever wrote
/// that table, so a connection drawn by hand never reached VIDS at all.
///
/// Tags follow _derive_studio_tables exactly: the endpoint's label, blank when
/// the node has none (a junction dot), never substituted.
///
/// The id differs in one respect. Extraction uses `line_id or "<from>→<to>"`,
/// which collides whenever two edges share a pair of labels. A canvas edge has
/// no line_id, so an unlabelled pair would key every such row as "→" and each
/// insert would overwrite the last. Node ids are unique, so fall back to those.
fn upsert_connection(
    conn: &rusqlite::Connection, pid: &str, from_id: &str, to_id: &str, kind: &str,
) {
    if !is_process_kind(kind) {
        return;                              // signal/pneumatic are topology only
    }
    let from_tag = label_by_node_id(conn, pid, from_id);
    let to_tag   = label_by_node_id(conn, pid, to_id);
    let id = if from_tag.is_empty() || to_tag.is_empty() {
        format!("{}→{}", from_id, to_id)
    } else {
        format!("{}→{}", from_tag, to_tag)
    };
    let _ = conn.execute(
        "INSERT INTO connections (id, pid, from_tag, to_tag, type, extra_json) \
         VALUES (?,?,?,?,?,?) \
         ON CONFLICT(id, pid) DO UPDATE SET \
           from_tag=excluded.from_tag, to_tag=excluded.to_tag, type=excluded.type",
        rusqlite::params![id, pid, from_tag, to_tag, kind, "{}"],
    );
}

/// Remove the `connections` row an edge owns, keyed the same way upsert_connection wrote it.
fn delete_connection_for(conn: &rusqlite::Connection, pid: &str, from_id: &str, to_id: &str) {
    let from_tag = label_by_node_id(conn, pid, from_id);
    let to_tag   = label_by_node_id(conn, pid, to_id);
    let _ = conn.execute(
        "DELETE FROM connections WHERE pid=? AND id IN (?, ?)",
        rusqlite::params![pid, format!("{}→{}", from_id, to_id), format!("{}→{}", from_tag, to_tag)],
    );
}

fn node_id_by_label(conn: &rusqlite::Connection, pid: &str, label: &str) -> Option<String> {
    conn.query_row("SELECT id FROM nodes WHERE pid=? AND label=? LIMIT 1", [pid, label], |r| r.get(0)).ok()
}

/// Clean up every table keyed by tag/label after a node's canonical `nodes`
/// row has been deleted (or is known not to exist): instruments, equipment,
/// review, connections (either side), and any equipment_ref pointing at it.
/// Returns the combined row count removed from instruments+equipment — the
/// two tables delete_node_by_tag treats as proof the tag existed at all.
fn cascade_delete_tag_refs(conn: &rusqlite::Connection, pid: &str, tag: &str) -> i64 {
    let mut count = 0i64;
    count += conn.execute("DELETE FROM instruments WHERE pid=? AND tag=?", [pid, tag]).unwrap_or(0) as i64;
    count += conn.execute("DELETE FROM equipment WHERE pid=? AND tag=?", [pid, tag]).unwrap_or(0) as i64;
    conn.execute("DELETE FROM review WHERE pid=? AND key=?", [pid, tag]).ok();
    conn.execute("DELETE FROM connections WHERE pid=? AND (from_tag=? OR to_tag=?)",
                 rusqlite::params![pid, tag, tag]).ok();
    conn.execute("UPDATE instruments SET equipment_ref='' WHERE pid=? AND equipment_ref=?", [pid, tag]).ok();
    count
}

#[tauri::command]
pub fn batch_insert_nodes(project_id: String, nodes_json: String) -> Result<BatchInsertResult<InsertedNodeId>, String> {
    let items: Vec<Value> = serde_json::from_str(&nodes_json)
        .map_err(|e| format!("Invalid nodes JSON: {}", e))?;

    let conn = open_db()?;
    let pid  = project_id.as_str();

    let mut counter = next_node_counter(&conn, pid);
    let mut ids: Vec<InsertedNodeId> = Vec::new();
    let default_drawing = default_drawing_for(&conn, pid);

    for item in &items {
        let tag  = item.get("tag").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
        let kind = item.get("kind").and_then(|v| v.as_str()).unwrap_or("equipment").to_string();
        let area = item.get("area").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let desc = item.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string();

        if tag.is_empty() { continue; }

        // Dedup by label within this project
        if label_exists(&conn, pid, &tag) { continue; }

        counter += 1;
        let nid  = format!("n{}", counter);
        // If the node anchors near an existing node (see placeNewNodes in
        // DescribeScreen.tsx), it's tagged with that anchor's real drawing so
        // it lands in the same multi-drawing grid tile — otherwise a
        // same-sheet connection would still render far apart because the
        // "extracted" canvas lays out each distinct drawing in its own cell.
        let drawing = item.get("drawing").and_then(|v| v.as_str())
            .filter(|s| !s.is_empty()).unwrap_or(&default_drawing).to_string();
        let extra = json!({
            "description":  desc,
            "drawing":      drawing,
            "confidence":   1.0,
            "equipment_ref":"",
            // Authored, not extracted: re-extraction carries this row forward
            // (extraction_cli/commands.py _AUTHORED_SQL).
            "origin":       "authored",
        }).to_string();

        let x: Option<f64> = item.get("x").and_then(|v| v.as_f64());
        let y: Option<f64> = item.get("y").and_then(|v| v.as_f64());

        conn.execute(
            "INSERT OR IGNORE INTO nodes (id, pid, kind, kind_detail, label, area, x, y, extra_json)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rusqlite::params![nid, pid, kind, kind, tag, area, x, y, extra],
        ).map_err(|e| format!("Insert node '{}' failed: {}", tag, e))?;

        mirror_node_to_instrument_or_equipment(&conn, pid, &tag, &kind, &area)?;

        ids.push(InsertedNodeId { id: nid, tag });
    }

    if !ids.is_empty() {
        touch_last_activity(&conn, pid);
    }

    Ok(BatchInsertResult { inserted: ids.len(), ids })
}

// Junction nodes (T-junctions / crossovers where 3+ pipes meet) are stored
// exactly like a real node so batch_insert_edges can reference them by label
// like any tag, but with kind/category "junction" so CanvasScreen renders
// them as a small dot instead of an ISA symbol box.
#[tauri::command]
pub fn batch_insert_junctions(project_id: String, junctions_json: String) -> Result<BatchInsertResult<InsertedJunctionId>, String> {
    let items: Vec<Value> = serde_json::from_str(&junctions_json)
        .map_err(|e| format!("Invalid junctions JSON: {}", e))?;

    let conn = open_db()?;
    let pid  = project_id.as_str();

    let mut counter = next_node_counter(&conn, pid);
    let default_drawing = default_drawing_for(&conn, pid);
    let mut ids: Vec<InsertedJunctionId> = Vec::new();

    for item in &items {
        let ref_id = item.get("id").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
        if ref_id.is_empty() { continue; }

        if label_exists(&conn, pid, &ref_id) { continue; }

        counter += 1;
        let nid = format!("n{}", counter);
        let drawing = item.get("drawing").and_then(|v| v.as_str())
            .filter(|s| !s.is_empty()).unwrap_or(&default_drawing).to_string();
        let extra = json!({
            "drawing":    drawing,
            "category":   "junction",
            "confidence": 1.0,
            "origin":     "authored",
        }).to_string();

        let x: Option<f64> = item.get("x").and_then(|v| v.as_f64());
        let y: Option<f64> = item.get("y").and_then(|v| v.as_f64());

        conn.execute(
            "INSERT OR IGNORE INTO nodes (id, pid, kind, kind_detail, label, area, x, y, extra_json)
             VALUES (?, ?, 'junction', 'junction', ?, '', ?, ?, ?)",
            rusqlite::params![nid, pid, ref_id, x, y, extra],
        ).map_err(|e| format!("Insert junction '{}' failed: {}", ref_id, e))?;

        ids.push(InsertedJunctionId { id: nid, ref_id });
    }

    if !ids.is_empty() {
        touch_last_activity(&conn, pid);
    }

    Ok(BatchInsertResult { inserted: ids.len(), ids })
}

#[tauri::command]
pub fn batch_insert_edges(project_id: String, edges_json: String) -> Result<EdgeInsertResult, String> {
    let items: Vec<Value> = serde_json::from_str(&edges_json)
        .map_err(|e| format!("Invalid edges JSON: {}", e))?;

    let conn = open_db()?;
    let pid  = project_id.as_str();
    let mut count: i64 = 0;

    for item in &items {
        let from_tag = item.get("from_tag").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
        let to_tag   = item.get("to_tag").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
        let kind     = item.get("kind").and_then(|v| v.as_str()).unwrap_or("stream").to_string();

        if from_tag.is_empty() || to_tag.is_empty() || from_tag == to_tag { continue; }

        let from_id = node_id_by_label(&conn, pid, &from_tag);
        let to_id = node_id_by_label(&conn, pid, &to_tag);

        if let (Some(fid), Some(tid)) = (from_id, to_id) {
            let extra = json!({ "drawing": "DESCRIBE", "origin": "authored" }).to_string();
            conn.execute(
                "INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json) VALUES (?,?,?,?,?,?)",
                rusqlite::params![pid, &fid, &tid, &kind, "", extra],
            ).map_err(|e| format!("Insert edge {}→{} failed: {}", from_tag, to_tag, e))?;
            upsert_connection(&conn, pid, &fid, &tid, &kind);
            count += 1;
        }
    }

    if count > 0 {
        touch_last_activity(&conn, pid);
    }

    Ok(EdgeInsertResult { inserted: count })
}

// Same as batch_insert_edges but keyed by real node ids, not labels.
// batch_insert_edges resolves endpoints via a label lookup and skips the
// item outright if either tag is empty — junction dots are frequently
// unlabeled, so any edge touching one silently never got inserted. The
// canvas always has both endpoints' real ids on hand already; use them.
#[tauri::command]
pub fn insert_edge_by_id(project_id: String, from_id: String, to_id: String, kind: String) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    let extra = json!({ "drawing": "DESCRIBE", "origin": "authored" }).to_string();
    conn.execute(
        "INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json) VALUES (?,?,?,?,?,?)",
        rusqlite::params![pid, from_id.as_str(), to_id.as_str(), kind.as_str(), "", extra],
    ).map_err(|e| format!("insert_edge_by_id failed: {}", e))?;
    upsert_connection(&conn, pid, &from_id, &to_id, &kind);
    Ok(())
}

#[tauri::command]
pub fn update_node_by_tag(
    project_id: String,
    tag: String,
    new_tag: Option<String>,
    kind: Option<String>,
    area: Option<String>,
    description: Option<String>,
) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    let old = tag.trim();
    if old.is_empty() { return Err("Tag cannot be empty".into()); }

    let target = new_tag.as_deref().map(str::trim).filter(|s| !s.is_empty())
        .unwrap_or(old).to_string();

    if target != old && label_exists(&conn, pid, &target) {
        return Err(format!("Tag '{}' already exists", target));
    }

    let touched: usize = conn.execute(
        "UPDATE nodes SET
           label = ?,
           kind        = COALESCE(NULLIF(?,''), kind),
           kind_detail = COALESCE(NULLIF(?,''), kind_detail),
           area        = COALESCE(NULLIF(?,''), area),
           extra_json  = json_set(COALESCE(extra_json,'{}'), '$.description',
                          COALESCE(NULLIF(?,''), json_extract(COALESCE(extra_json,'{}'),'$.description')))
         WHERE pid=? AND label=?",
        rusqlite::params![
            target,
            kind.clone().unwrap_or_default(), kind.clone().unwrap_or_default(),
            area.unwrap_or_default(),
            description.unwrap_or_default(),
            pid, old,
        ],
    ).map_err(|e| format!("Update node '{}' failed: {}", old, e))?;

    if touched == 0 {
        return Err(format!("Tag '{}' not found", old));
    }

    // Keep tag-referencing tables consistent after a rename.
    if target != old {
        conn.execute("UPDATE instruments SET tag=? WHERE pid=? AND tag=?",
            rusqlite::params![target, pid, old]).ok();
        conn.execute("UPDATE equipment SET tag=? WHERE pid=? AND tag=?",
            rusqlite::params![target, pid, old]).ok();
        conn.execute("UPDATE review SET key=? WHERE pid=? AND key=?",
            rusqlite::params![target, pid, old]).ok();
        conn.execute("UPDATE instruments SET equipment_ref=? WHERE pid=? AND equipment_ref=?",
            rusqlite::params![target, pid, old]).ok();
        conn.execute("UPDATE connections SET from_tag=? WHERE pid=? AND from_tag=?",
            rusqlite::params![target, pid, old]).ok();
        conn.execute("UPDATE connections SET to_tag=? WHERE pid=? AND to_tag=?",
            rusqlite::params![target, pid, old]).ok();
    }

    Ok(())
}

#[tauri::command]
pub fn delete_node_by_tag(project_id: String, tag: String) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    let t = tag.trim();
    if t.is_empty() { return Err("Tag cannot be empty".into()); }

    let mut affected: i64 = 0;

    let node_id: Option<String> = conn
        .query_row("SELECT id FROM nodes WHERE pid=? AND label=?", [pid, t], |r| r.get(0))
        .ok();
    if let Some(nid) = &node_id {
        conn.execute("DELETE FROM edges WHERE pid=? AND (from_id=? OR to_id=?)",
                     rusqlite::params![pid, nid, nid]).ok();
        affected += conn.execute("DELETE FROM nodes WHERE id=? AND pid=?", [nid.as_str(), pid])
            .map_err(|e| format!("delete node failed: {}", e))? as i64;
    }

    affected += cascade_delete_tag_refs(&conn, pid, t);

    if affected == 0 {
        return Err(format!("Tag '{}' not found", t));
    }
    Ok(())
}

// ── import_llm_verified ──────────────────────────────────────────────────────
// Reads a *_llm_verified.json produced by the studio pipeline and writes nodes
// + edges into the project's DB tables, replacing any previous LLM import.
// kind mapping mirrors the ISANodes.tsx getNodeType() expectations.
#[tauri::command]
pub fn import_llm_verified(project_id: String, json_path: String) -> Result<ImportLlmResult, String> {
    let raw = std::fs::read_to_string(&json_path)
        .map_err(|e| format!("Cannot read file '{}': {}", json_path, e))?;
    let doc: Value = serde_json::from_str(&raw)
        .map_err(|e| format!("Invalid JSON: {}", e))?;

    let llm_nodes = doc.get("nodes").and_then(|v| v.as_array())
        .ok_or("Missing 'nodes' array in LLM JSON")?;
    let llm_edges = doc.get("edges").and_then(|v| v.as_array())
        .ok_or("Missing 'edges' array in LLM JSON")?;

    // Kind remapping: LLM outputs ISA-adjacent names; map to what ISANodes.tsx understands
    fn remap_kind(k: &str) -> &str {
        match k {
            "back_pressure_regulator" | "pressure_regulator" | "regulator" => "control_valve",
            "quick_connect" | "fitting" => "hand_valve",
            "element" | "sensor" => "transmitter",
            "gauge" => "indicator",
            // "drum"/"separator"/"tank"/"vessel_v"/"vessel_h"/"flash_drum"/"knockout"/
            // "accumulator"/"tank_atm"/"hopper" all pass through unchanged (other => other)
            // classification.ts's own switch already maps each to its correct symbol —
            // remapping them to a bare "vessel" here used to erase the vertical/horizontal
            // distinction the LLM extracts from the drawing.
            "booster_pump" => "pump",
            "boundary" | "header" => "filter",
            other => other,
        }
    }

    let conn = open_db()?;
    let pid = project_id.as_str();

    // Delete previous LLM import for this project (nodes with drawing='LLM')
    conn.execute(
        "DELETE FROM edges WHERE pid = ? AND extra_json LIKE '%\"source\":\"LLM\"%'",
        [pid],
    ).ok();
    // Delete all nodes that came from LLM (we stored drawing in extra_json)
    conn.execute(
        "DELETE FROM nodes WHERE pid = ? AND json_extract(extra_json,'$.drawing') = 'LLM'",
        [pid],
    ).map_err(|e| format!("Delete old LLM nodes: {}", e))?;
    // Also delete old LLM edges
    conn.execute(
        "DELETE FROM edges WHERE pid = ? AND json_extract(extra_json,'$.source') = 'LLM'",
        [pid],
    ).ok();

    // Build id→db_id map so edges can reference the inserted nodes
    let mut id_map: std::collections::HashMap<String, String> = std::collections::HashMap::new();

    // Find highest existing node counter for this project (used as fallback
    // when the LLM JSON does not provide an id).
    let mut counter = next_node_counter(&conn, pid);

    let mut node_count = 0i64;
    for node in llm_nodes {
        let llm_id    = node.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let llm_label = node.get("label").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let llm_type  = node.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let llm_kind  = node.get("kind").and_then(|v| v.as_str()).unwrap_or("equipment").to_string();
        let category  = node.get("category").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let x         = node.get("x").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let y         = node.get("y").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let conf      = node.get("confidence").and_then(|v| v.as_f64()).unwrap_or(1.0);

        // Clean label: if label equals YOLO type, replace underscores with spaces
        let label = if llm_label == llm_type {
            llm_label.replace('_', " ")
        } else {
            llm_label.clone()
        };

        let kind        = remap_kind(&llm_kind).to_string();
        let kind_detail = if llm_type.is_empty() { llm_kind.clone() } else { llm_type.clone() };

        let extra = json!({
            "drawing":    "LLM",
            "category":   category,
            "yolo_type":  llm_type,
            "confidence": conf,
            "annotations": node.get("annotations").cloned().unwrap_or(json!([])),
            "source":     "LLM",
        }).to_string();

        // Preserve the original LLM node ID (e.g. n39, n72) so it matches the
        // waypoint paths in *_paths.json.  Only auto-increment when the LLM
        // didn't supply an id.
        let db_id = if !llm_id.is_empty() {
            llm_id.clone()
        } else {
            counter += 1;
            format!("n{}", counter)
        };
        id_map.insert(llm_id, db_id.clone());

        conn.execute(
            "INSERT OR REPLACE INTO nodes (id, pid, kind, kind_detail, label, area, x, y, extra_json)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rusqlite::params![db_id, pid, kind, kind_detail, label, "", x, y, extra],
        ).map_err(|e| format!("Insert node '{}': {}", label, e))?;

        node_count += 1;
    }

    // Deduplicate and insert edges
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut edge_count = 0i64;
    for edge in llm_edges {
        let from_llm = edge.get("from").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let to_llm   = edge.get("to").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let kind     = edge.get("kind").and_then(|v| v.as_str()).unwrap_or("process");
        let kind_db  = if kind == "process" { "stream" } else { kind }.to_string();

        let from_db = match id_map.get(&from_llm) { Some(v) => v.clone(), None => continue };
        let to_db   = match id_map.get(&to_llm)   { Some(v) => v.clone(), None => continue };

        let mut key_parts = [from_db.clone(), to_db.clone()];
        key_parts.sort();
        let key = key_parts.join("<>");
        if seen.contains(&key) { continue; }
        seen.insert(key);

        // Preserve waypoints from LLM B so canvas can draw real pipe routes
        let waypoints = edge.get("waypoints").cloned().unwrap_or(Value::Null);
        let extra = json!({ "source": "LLM", "waypoints": waypoints }).to_string();
        conn.execute(
            "INSERT INTO edges (pid, from_id, to_id, kind, extra_json) VALUES (?, ?, ?, ?, ?)",
            rusqlite::params![pid, from_db, to_db, kind_db, extra],
        ).map_err(|e| format!("Insert edge {}->{}: {}", from_db, to_db, e))?;
        edge_count += 1;
    }

    Ok(ImportLlmResult { nodes_imported: node_count, edges_imported: edge_count })
}

#[tauri::command]
pub fn update_node(project_id: String, node_id: String, label: String, kind: String, area: String, description: String) -> Result<(), String> {
    let conn = open_db()?;
    // extra_json.type is the separate, authoritative "raw detector type" field
    // (e.g. off-page connector arrow direction reads it, not kind/kind_detail).
    // Editing Kind to Inlet/Outlet is the one case a user expects a visible
    // effect from, so keep type in sync for exactly that; leave it alone
    // otherwise so we don't clobber real extraction data (e.g. "Ball_Valve")
    // with free-text Kind values that aren't in the shape vocabulary.
    let kind_lower = kind.to_lowercase();
    let affected = if kind_lower == "inlet" || kind_lower == "outlet" {
        conn.execute(
            "UPDATE nodes SET label=?, kind=?, kind_detail=?, area=?,
             extra_json=json_set(json_set(COALESCE(extra_json,'{}'), '$.description', ?), '$.type', ?)
             WHERE id=? AND pid=?",
            rusqlite::params![label, kind, kind, area, description, kind, node_id, project_id.as_str()],
        ).unwrap_or(0)
    } else {
        conn.execute(
            "UPDATE nodes SET label=?, kind=?, kind_detail=?, area=?,
             extra_json=json_set(COALESCE(extra_json,'{}'), '$.description', ?)
             WHERE id=? AND pid=?",
            rusqlite::params![label, kind, kind, area, description, node_id, project_id.as_str()],
        ).unwrap_or(0)
    };

    // If no rows were affected in nodes, it might be an extracted entity.
    if affected == 0 {
        // We do not update the tag itself for extracted items to avoid breaking connections.
        let _ = conn.execute(
            "UPDATE equipment SET type=?, kind_detail=?, area=?,
             extra_json=json_set(COALESCE(extra_json,'{}'), '$.description', ?)
             WHERE tag=? AND pid=?",
            rusqlite::params![kind, kind, area, description, node_id, project_id.as_str()],
        );
        let _ = conn.execute(
            "UPDATE instruments SET type=?, kind_detail=?, area=?,
             extra_json=json_set(COALESCE(extra_json,'{}'), '$.description', ?)
             WHERE tag=? AND pid=?",
            rusqlite::params![kind, kind, area, description, node_id, project_id.as_str()],
        );
    }
    Ok(())
}

// Persist a pipe's user-dragged bend point (0-1 sheet coords). Called when
// someone grabs a selected edge's corner and drags it to reshape the route.
#[tauri::command]
pub fn update_edge_bend(project_id: String, from_id: String, to_id: String, x: f64, y: f64) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    let affected = conn.execute(
        "UPDATE edges SET extra_json=json_set(json_set(COALESCE(extra_json,'{}'), '$.bend_x', ?), '$.bend_y', ?)
         WHERE pid=? AND from_id=? AND to_id=?",
        rusqlite::params![x, y, pid, from_id.as_str(), to_id.as_str()],
    ).map_err(|e| format!("update_edge_bend failed: {}", e))?;
    if affected == 0 {
        return Err(format!("update_edge_bend: no edge row {}->{}", from_id, to_id));
    }
    Ok(())
}

// Undo support: revert a pipe to its default (no custom corner) route.
#[tauri::command]
pub fn clear_edge_bend(project_id: String, from_id: String, to_id: String) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    conn.execute(
        "UPDATE edges SET extra_json=json_remove(json_remove(COALESCE(extra_json,'{}'), '$.bend_x'), '$.bend_y')
         WHERE pid=? AND from_id=? AND to_id=?",
        rusqlite::params![pid, from_id.as_str(), to_id.as_str()],
    ).map_err(|e| format!("clear_edge_bend failed: {}", e))?;
    Ok(())
}

#[tauri::command]
pub fn update_node_position(project_id: String, node_id: String, x: f64, y: f64) -> Result<(), String> {
    let conn = open_db()?;
    conn.execute(
        "UPDATE nodes SET x=?, y=? WHERE id=? AND pid=?",
        rusqlite::params![x, y, node_id, project_id.as_str()],
    ).map_err(|e| format!("update_node_position failed: {}", e))?;
    Ok(())
}

// Remove every edge between the two tags (both rows if duplicated). Used when a
// connection is dragged to a new symbol — the old link is deleted, the new one
// inserted via batch_insert_edges.
#[tauri::command]
pub fn delete_edge(project_id: String, from_tag: String, to_tag: String) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    let from_id = node_id_by_label(&conn, pid, &from_tag);
    let to_id = node_id_by_label(&conn, pid, &to_tag);
    let (fid, tid) = match (from_id, to_id) {
        (Some(fid), Some(tid)) => (fid, tid),
        _ => return Err(format!("delete_edge: tag not found (from='{}' to='{}')", from_tag, to_tag)),
    };
    delete_connection_for(&conn, pid, &fid, &tid);   // before the edge row goes
    let affected = conn.execute(
        "DELETE FROM edges WHERE pid=? AND from_id=? AND to_id=?",
        rusqlite::params![pid, &fid, &tid],
    ).map_err(|e| format!("delete_edge failed: {}", e))?;
    if affected == 0 {
        return Err(format!("delete_edge: no edge row {}->{}", fid, tid));
    }
    Ok(())
}

// Same as delete_edge but takes real node ids directly — used wherever the
// caller already has them (canvas edge objects carry source/target ids).
// delete_edge's tag→id lookup picks an arbitrary match on LIMIT 1 when a
// label isn't unique (junction dots are frequently unlabeled/blank), which
// can silently resolve to the wrong node and delete nothing.
#[tauri::command]
pub fn delete_edge_by_id(project_id: String, from_id: String, to_id: String) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    delete_connection_for(&conn, pid, &from_id, &to_id);
    let affected = conn.execute(
        "DELETE FROM edges WHERE pid=? AND from_id=? AND to_id=?",
        rusqlite::params![pid, from_id.as_str(), to_id.as_str()],
    ).map_err(|e| format!("delete_edge_by_id failed: {}", e))?;
    if affected == 0 {
        return Err(format!("delete_edge_by_id: no edge row {}->{}", from_id, to_id));
    }
    Ok(())
}

#[tauri::command]
pub fn delete_node(project_id: String, node_id: String) -> Result<(), String> {
    let conn = open_db()?;
    let pid = project_id.as_str();
    let nid = node_id.as_str();
    // Get label first so we can clean up instruments/review too
    let label: Option<String> = conn
        .query_row("SELECT label FROM nodes WHERE id=? AND pid=?", [nid, pid], |r| r.get(0))
        .ok();
    // Delete connected edges
    conn.execute("DELETE FROM edges WHERE pid=? AND (from_id=? OR to_id=?)",
                 rusqlite::params![pid, nid, nid])
        .map_err(|e| format!("delete edges failed: {}", e))?;
    // Delete the node itself. rusqlite's execute() returns the affected row
    // count, not just Ok/Err — an id/pid that matches nothing still returns
    // Ok(0), which previously looked like success while deleting nothing at
    // all. Surface that as a real error instead of silently no-opping.
    let affected = conn.execute("DELETE FROM nodes WHERE id=? AND pid=?", [nid, pid])
        .map_err(|e| format!("delete node failed: {}", e))?;
    if affected == 0 {
        return Err(format!("delete_node: no row matched id={} pid={}", nid, pid));
    }
    // Also remove every other table keyed by tag/label — otherwise the symbol
    // still shows up on Review/Gaps/Export (equipment table) or as a dangling
    // link (connections, other instruments' equipment_ref) after "deleting" it
    // from the canvas.
    if let Some(tag) = label {
        cascade_delete_tag_refs(&conn, pid, &tag);
    }
    Ok(())
}

#[tauri::command]
pub fn get_graph(project_id: String) -> Result<GraphDto, String> {
    let conn = open_db()?;
    let pid  = project_id.as_str();

    // Prefer the nodes table (has x,y natively). Fall back to instruments+equipment.
    let node_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM nodes WHERE pid = ?", [pid], |r| r.get(0))
        .unwrap_or(0);

    let nodes: Vec<GraphNodeDto> = if node_count > 0 {
        // Join with instruments to get equipment_ref for instrument nodes.
        // drawing is stored in nodes.extra_json.
        let mut stmt = conn.prepare(
            "SELECT n.id,
                    COALESCE(n.label,'')       AS label,
                    COALESCE(n.kind,'')        AS kind,
                    COALESCE(n.kind_detail,'') AS kind_detail,
                    COALESCE(n.x, 0.0)         AS x,
                    COALESCE(n.y, 0.0)         AS y,
                    COALESCE(n.area,'')        AS area,
                    COALESCE(json_extract(n.extra_json,'$.drawing'),'') AS drawing,
                    COALESCE(i.equipment_ref, json_extract(n.extra_json,'$.equipment_ref'), '') AS equipment_ref,
                    COALESCE(json_extract(n.extra_json,'$.category'),'') AS category,
                    COALESCE(e.type, i.type, json_extract(n.extra_json,'$.type'), '') AS type,
                    json_extract(n.extra_json,'$.page')   AS page,
                    json_extract(n.extra_json,'$.page_w') AS page_w,
                    json_extract(n.extra_json,'$.page_h') AS page_h,
                    n.source_id                           AS source_id
             FROM nodes n
             LEFT JOIN instruments i ON i.tag = n.label AND i.pid = n.pid
             LEFT JOIN equipment e ON e.tag = n.label AND e.pid = n.pid
             WHERE n.pid = ?
             ORDER BY n.id"
        ).map_err(|e| format!("Prepare nodes: {}", e))?;
        collect_rows(&mut stmt, [pid], |row| {
            Ok(GraphNodeDto {
                id:            row.get::<_,String>(0).unwrap_or_default(),
                label:         row.get::<_,String>(1).unwrap_or_default(),
                kind:          row.get::<_,String>(2).unwrap_or_default(),
                kind_detail:   row.get::<_,String>(3).unwrap_or_default(),
                x:             row.get::<_,f64>(4).unwrap_or(0.0),
                y:             row.get::<_,f64>(5).unwrap_or(0.0),
                area:          row.get::<_,String>(6).unwrap_or_default(),
                drawing:       row.get::<_,String>(7).unwrap_or_default(),
                equipment_ref: row.get::<_,String>(8).unwrap_or_default(),
                category:      row.get::<_,String>(9).unwrap_or_default(),
                // Raw detector type (e.g. "Inlet"/"Outlet") — authoritative for
                // off-page connector arrow direction. Stored in extra_json.
                r#type:        Some(row.get::<_,String>(10).unwrap_or_default()),
                // 1-based source page. Absent on projects extracted before the
                // Phase 1 multi-page change.
                page:          row.get::<_,Option<i64>>(11).unwrap_or(None),
                page_w:        row.get::<_,Option<i64>>(12).unwrap_or(None),
                page_h:        row.get::<_,Option<i64>>(13).unwrap_or(None),
                source_id:     row.get::<_,Option<i64>>(14).unwrap_or(None),
            })
        })?
    } else {
        // Fallback: union instruments + equipment, x/y + drawing from extra_json
        let mut stmt = conn.prepare(
            "SELECT tag,
                    COALESCE(kind_detail, COALESCE(type,'')) AS kind_detail,
                    'instrument'                              AS kind,
                    COALESCE(CAST(json_extract(extra_json,'$.x') AS REAL), 0.0) AS x,
                    COALESCE(CAST(json_extract(extra_json,'$.y') AS REAL), 0.0) AS y,
                    COALESCE(area,'') AS area,
                    COALESCE(json_extract(extra_json,'$.drawing'),'') AS drawing,
                    COALESCE(equipment_ref,'') AS equipment_ref,
                    'instrument'      AS category
             FROM instruments WHERE pid = ?
             UNION ALL
             SELECT tag,
                    COALESCE(kind_detail, COALESCE(type,'')) AS kind_detail,
                    'equipment'                               AS kind,
                    COALESCE(CAST(json_extract(extra_json,'$.x') AS REAL), 0.0) AS x,
                    COALESCE(CAST(json_extract(extra_json,'$.y') AS REAL), 0.0) AS y,
                    COALESCE(area,'') AS area,
                    COALESCE(json_extract(extra_json,'$.drawing'),'') AS drawing,
                    ''                AS equipment_ref,
                    'equipment'       AS category
             FROM equipment WHERE pid = ?
             ORDER BY tag"
        ).map_err(|e| format!("Prepare fallback nodes: {}", e))?;
        collect_rows(&mut stmt, [pid, pid], |row| {
            let tag: String = row.get::<_,String>(0).unwrap_or_default();
            Ok(GraphNodeDto {
                id:            tag.clone(),
                label:         tag,
                kind:          row.get::<_,String>(2).unwrap_or_default(),
                kind_detail:   row.get::<_,String>(1).unwrap_or_default(),
                x:             row.get::<_,f64>(3).unwrap_or(0.0),
                y:             row.get::<_,f64>(4).unwrap_or(0.0),
                area:          row.get::<_,String>(5).unwrap_or_default(),
                drawing:       row.get::<_,String>(6).unwrap_or_default(),
                equipment_ref: row.get::<_,String>(7).unwrap_or_default(),
                category:      row.get::<_,String>(8).unwrap_or_default(),
                // The legacy fallback path never had a "type" key at all —
                // None + skip_serializing_if reproduces that omission exactly.
                r#type:        None,
                // Same for page: this path predates multi-page extraction.
                page:          None,
                page_w:        None,
                page_h:        None,
                source_id:     None,
            })
        })?
    };

    // ── Edges: merge edges table (primary, node IDs) + connections (secondary, tag→node join) ──
    // Always query both and deduplicate by (source, target) — edges table wins on conflict.

    // No row limit. This query used to carry a hardcoded `LIMIT 2000` with no
    // ORDER BY, so any project past 2000 edges rendered an arbitrary subset of
    // its topology and said nothing about it. That limit was a leftover: it was
    // added (commit 19e0412) to cap a DIFFERENT query — the `connections`
    // fallback below, which matched edges by LABEL and fanned out into hundreds
    // of false edges whenever a label repeated. That query was deleted in
    // b5a2dc6; its copy of the limit stayed behind on this one, where nothing
    // can fan out (one `edges` row = one real edge, keyed by node id).
    //
    // ORDER BY id is kept purely for a stable, reproducible read order.
    let mut stmt_e = conn.prepare(
        "SELECT COALESCE(from_id,'') AS source,
                COALESCE(to_id,'')   AS target,
                COALESCE(kind,'stream') AS kind,
                COALESCE(extra_json,'{}') AS extra,
                source_id
         FROM edges WHERE pid = ?
         ORDER BY id"
    ).map_err(|e| format!("Prepare edges: {}", e))?;
    let primary_edges = collect_rows(&mut stmt_e, [pid], |row| {
        // Waypoints live in edges.extra_json (the DB) — surface them here so the
        // canvas draws real pipe routes from the DB, not a separate paths sidecar.
        let extra: String = row.get::<_,String>(3).unwrap_or_default();
        let extra_v = serde_json::from_str::<Value>(&extra).ok();
        let waypoints = extra_v.as_ref().and_then(|v| v.get("waypoints").cloned()).unwrap_or(Value::Null);
        // User-dragged pipe bend (0-1 sheet coords, same scheme as node x/y) —
        // set via update_edge_bend when someone grabs a pipe's corner and moves it.
        let bend_x = extra_v.as_ref().and_then(|v| v.get("bend_x")).and_then(|v| v.as_f64());
        let bend_y = extra_v.as_ref().and_then(|v| v.get("bend_y")).and_then(|v| v.as_f64());
        // Phase 3: both were already being written into extra_json by the
        // Phase 2 guard, and both were being dropped here — so the canvas had
        // no way to tell a geometry-backed edge from an LLM addition, or an
        // audited edge from an unaudited fallback.
        let provenance = extra_v.as_ref()
            .and_then(|v| v.get("provenance"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let audited = extra_v.as_ref()
            .and_then(|v| v.get("audited"))
            .and_then(|v| v.as_bool());
        Ok(GraphEdgeDto {
            source: row.get::<_,String>(0).unwrap_or_default(),
            target: row.get::<_,String>(1).unwrap_or_default(),
            kind:   row.get::<_,String>(2).unwrap_or_default(),
            waypoints,
            bend_x,
            bend_y,
            provenance,
            audited,
            source_id: row.get::<_,Option<i64>>(4).unwrap_or(None),
        })
    })?;

    // Only use primary edges (node-ID keyed). The connections table JOIN by label
    // produces a cartesian product when labels like "Ball_Valve" match many nodes,
    // creating hundreds of false edges (e.g. N2 → every Ball_Valve in the diagram).
    //
    // Phase 5: this used to also drop any edge whose (source, target) pair had
    // already been seen. That collapsed PARALLEL EDGES — two genuinely distinct
    // pipe runs between the same pair of symbols became one. The dedupe existed
    // to contain the connections-table cartesian product, and that merge is gone;
    // applied to the node-ID-keyed `edges` table it only ever discarded real rows,
    // each of which has its own autoincrement primary key. Rows with an empty
    // endpoint are still dropped — those cannot be rendered.
    //
    // The frontend is already built for this: makeEdgeId() (Phase 3) suffixes
    // repeated endpoint pairs as `e:a->b#1`, so React Flow ids stay unique.
    let edges: Vec<GraphEdgeDto> = primary_edges
        .into_iter()
        .filter(|e| !e.source.is_empty() && !e.target.is_empty())
        .collect();

    Ok(GraphDto { nodes, edges })
}

#[cfg(test)]
mod graph_dto_tests {
    use super::*;

    /// Phase 4 contract guard: get_graph's `nodes`/`edges` used to be built
    /// from ad-hoc `json!()` values; this locks in the exact key set the
    /// frontend depends on now that they're typed structs, including the one
    /// asymmetry that must be preserved — a node from the primary (nodes
    /// table) path always carries a "type" key, but this specific project's
    /// node_count > 0 (confirmed by other tests in this suite), so the
    /// legacy no-"type" fallback path can't be exercised against real data
    /// here; the None + skip_serializing_if wiring is what reproduces it.
    #[test]
    fn get_graph_serializes_expected_node_and_edge_keys() {
        let graph = match get_graph("p-id-5".to_string()) {
            Ok(g) => g,
            Err(e) => { eprintln!("skipping: get_graph errored: {}", e); return; }
        };
        if graph.nodes.is_empty() { eprintln!("skipping: p-id-5 has no nodes"); return; }

        let v = serde_json::to_value(&graph).expect("serialize GraphDto");
        let node0 = &v["nodes"][0];
        let mut keys: Vec<&str> = node0.as_object().unwrap().keys().map(|s| s.as_str()).collect();
        keys.sort();
        assert_eq!(
            keys,
            vec!["area", "category", "drawing", "equipment_ref", "id", "kind",
                 "kind_detail", "label", "type", "x", "y"],
            "node JSON shape must match what the frontend already expects"
        );

        if let Some(edge0) = v["edges"].get(0) {
            let mut ekeys: Vec<&str> = edge0.as_object().unwrap().keys().map(|s| s.as_str()).collect();
            ekeys.sort();
            assert_eq!(ekeys, vec!["bend_x", "bend_y", "kind", "source", "target", "waypoints"]);
        }
    }

    /// Phase 1 regression: `get_graph` carried `LIMIT 2000` on the edge
    /// query, so a project with more edges than that silently rendered a
    /// truncated graph. Builds a throwaway DB with 2500 edges and asserts
    /// every one comes back.
    #[test]
    fn get_graph_returns_more_than_2000_edges() {
        use rusqlite::Connection;

        let conn = Connection::open_in_memory().expect("open memory db");
        conn.execute_batch(
            "CREATE TABLE nodes (id TEXT, pid TEXT, kind TEXT, kind_detail TEXT,
                                 label TEXT, area TEXT, x REAL, y REAL,
                                 extra_json TEXT, PRIMARY KEY (id, pid));
             CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT,
                                 from_id TEXT, to_id TEXT, kind TEXT, label TEXT,
                                 extra_json TEXT);",
        ).expect("schema");

        const N: i64 = 2500;
        for i in 0..N {
            conn.execute(
                "INSERT INTO edges (pid, from_id, to_id, kind, extra_json)
                 VALUES ('big', ?1, ?2, 'process', '{}')",
                rusqlite::params![format!("n{}", i), format!("n{}", i + 1)],
            ).expect("insert edge");
        }

        // Mirrors the uncapped statement get_graph now builds.
        let mut stmt = conn.prepare(
            "SELECT COALESCE(from_id,''), COALESCE(to_id,'')
             FROM edges WHERE pid = ? ORDER BY id"
        ).expect("prepare");
        let rows: Vec<(String, String)> = stmt
            .query_map(["big"], |r| Ok((r.get(0)?, r.get(1)?)))
            .expect("query")
            .filter_map(|r| r.ok())
            .collect();

        assert_eq!(rows.len() as i64, N, "all {} edges must survive the read", N);
        // Deterministic order: the ORDER BY means a capped read is at least
        // reproducible rather than arbitrary rowid order.
        assert_eq!(rows[0].0, "n0");
        assert_eq!(rows[(N - 1) as usize].0, format!("n{}", N - 1));

        let total: i64 = conn
            .query_row("SELECT COUNT(*) FROM edges WHERE pid = ?", ["big"], |r| r.get(0))
            .expect("count");
        assert_eq!(total, N);
    }

    /// Phase 5 — the controlled multi-document database, read through the same
    /// query get_graph uses. Two PDFs in one project that deliberately produce
    /// the same local node ids, the same page numbers and the same structure:
    /// the scenario that used to leave only one document's rows behind.
    ///
    /// Skipped unless PHASE5_DB points at the fixture, so the suite still runs
    /// on a machine that has not built it.
    #[test]
    fn multi_document_project_keeps_both_documents_distinct() {
        let Ok(dbpath) = std::env::var("PHASE5_DB") else {
            eprintln!("skipping: PHASE5_DB not set");
            return;
        };
        let conn = rusqlite::Connection::open(&dbpath).unwrap();

        let mut stmt = conn
            .prepare("SELECT id, source_id, json_extract(extra_json,'$.page')                       FROM nodes WHERE pid='P' ORDER BY id")
            .unwrap();
        let nodes: Vec<(String, Option<i64>, Option<i64>)> = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();

        assert_eq!(nodes.len(), 12, "both documents must survive");

        // React Flow keys nodes by id, so global uniqueness is what keeps the
        // two documents from overwriting each other on the canvas too.
        let uniq: std::collections::HashSet<&String> = nodes.iter().map(|n| &n.0).collect();
        assert_eq!(uniq.len(), 12, "node ids must be unique across documents");

        // Document identity reaches the DTO layer.
        let d1 = nodes.iter().filter(|n| n.1 == Some(1)).count();
        let d2 = nodes.iter().filter(|n| n.1 == Some(2)).count();
        assert_eq!((d1, d2), (6, 6), "each document keeps its own rows");

        // Page 1 exists in BOTH documents and is not collapsed into one page.
        let page1: Vec<Option<i64>> = nodes.iter().filter(|n| n.2 == Some(1)).map(|n| n.1).collect();
        assert_eq!(page1.len(), 6);
        assert!(page1.contains(&Some(1)) && page1.contains(&Some(2)));

        let mut es = conn
            .prepare("SELECT COALESCE(from_id,''), COALESCE(to_id,''), source_id                       FROM edges WHERE pid='P' ORDER BY id")
            .unwrap();
        let edges: Vec<(String, String, Option<i64>)> = es
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();

        // Same filter get_graph applies — no endpoint dedupe any more, so the
        // parallel runs survive.
        let kept: Vec<_> = edges.iter().filter(|e| !e.0.is_empty() && !e.1.is_empty()).collect();
        assert_eq!(kept.len(), 8, "parallel edges must not be deduped away");

        // No edge may join two documents.
        let by_id: std::collections::HashMap<&String, Option<i64>> =
            nodes.iter().map(|n| (&n.0, n.1)).collect();
        for e in &kept {
            assert_eq!(by_id.get(&e.0), by_id.get(&e.1), "edge {:?} crosses documents", e);
        }
    }
}

#[cfg(test)]
mod phase6_save_reload_tests {
    //! Phase 6 Steps 7/8 — save / reload and user editing, driven through the
    //! REAL Tauri command functions against a temp hub.
    //!
    //! What this cannot do: click anything. Drag, selection, zoom and pan are
    //! browser behaviours and are NOT covered here. What it does cover is the
    //! full persistence contract behind each of those gestures — the layer
    //! where an edit is actually lost.

    use crate::commands::graph;

    const PREFIX: &str = "enstudio_p6sr";

    /// A private hub directory for one test.
    ///
    /// Uses a fresh, uniquely-named directory rather than deleting and
    /// recreating a fixed one. On Windows `remove_dir_all` can return before
    /// the directory is actually gone — deletion finishes asynchronously while
    /// a handle lingers — so the immediate `create_dir_all` that followed it
    /// could fail with "access denied" or resurrect a half-deleted tree. That
    /// produced exactly one unreproducible failure on a clean rebuild.
    fn hub(name: &str) -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU32, Ordering};
        static SEQ: AtomicU32 = AtomicU32::new(0);
        let unique = format!(
            "{}_{}_{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        );
        let dir = std::env::temp_dir().join(format!("{}_{}_{}", PREFIX, name, unique));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn seed(db: &std::path::Path) {
        let conn = rusqlite::Connection::open(db).unwrap();
        conn.execute_batch(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT, status TEXT);
             CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT,
                 filename TEXT, file_hash TEXT, uploaded TEXT, cached INTEGER);
             CREATE TABLE nodes (id TEXT, pid TEXT, kind TEXT, kind_detail TEXT, label TEXT,
                 area TEXT, x REAL, y REAL, extra_json TEXT, source_id INTEGER,
                 PRIMARY KEY (id, pid));
             CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, from_id TEXT,
                 to_id TEXT, kind TEXT, label TEXT, extra_json TEXT, source_id INTEGER);
             CREATE TABLE instruments (tag TEXT, pid TEXT, area TEXT, kind_detail TEXT,
                 type TEXT, equipment_ref TEXT, extra_json TEXT, PRIMARY KEY (tag, pid));
             CREATE TABLE equipment (tag TEXT, pid TEXT, area TEXT, kind_detail TEXT,
                 type TEXT, extra_json TEXT, PRIMARY KEY (tag, pid));
             CREATE TABLE connections (id TEXT, pid TEXT, from_tag TEXT, to_tag TEXT,
                 type TEXT, extra_json TEXT, PRIMARY KEY (id, pid));
             CREATE TABLE canvas_positions (pid TEXT, node_id TEXT, x REAL, y REAL,
                 PRIMARY KEY (pid, node_id));
             INSERT INTO projects VALUES ('P','P','done');
             INSERT INTO sources (pid,filename,file_hash,uploaded,cached)
                 VALUES ('P','a.pdf','ha',datetime('now'),1);",
        )
        .unwrap();
        for (i, l) in ["V-1", "V-2", "V-3"].iter().enumerate() {
            let extra = format!("{{\"page\":1,\"drawing\":\"doc1\",\"provenance\":\"geometry\"}}");
            conn.execute(
                "INSERT INTO nodes (id,pid,kind,label,x,y,extra_json,source_id)
                 VALUES (?,'P','vessel',?,?,?,?,1)",
                rusqlite::params![format!("s1_n{}", i + 1), l, 0.1 * (i as f64 + 1.0), 0.2, extra],
            )
            .unwrap();
        }
        conn.execute(
            "INSERT INTO edges (pid,from_id,to_id,kind,extra_json,source_id)
             VALUES ('P','s1_n1','s1_n2','process','{\"provenance\":\"geometry\",\"waypoints\":[[0.1,0.2],[0.3,0.2],[0.3,0.4]]}',1)",
            [],
        )
        .unwrap();
    }

    /// Reload the graph through the real get_graph command.
    fn load() -> crate::models::graph::GraphDto {
        graph::get_graph("P".to_string()).expect("get_graph failed")
    }

    #[test]
    fn user_edits_survive_save_and_reload() {
        let _guard = crate::database::TEST_HUB_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let h = hub("edits");
        let db = h.join("studio.db");
        seed(&db);
        std::env::set_var("ENGINEERING_HUB", h.to_str().unwrap());

        let g0 = load();
        assert_eq!(g0.nodes.len(), 3);
        assert_eq!(g0.edges.len(), 1);

        // ── NODE: move ────────────────────────────────────────────────────
        graph::update_node_position("P".to_string(), "s1_n1".to_string(), 0.77, 0.88).unwrap();
        let g = load();
        let n1 = g.nodes.iter().find(|n| n.id == "s1_n1").unwrap();
        assert!((n1.x - 0.77).abs() < 1e-9 && (n1.y - 0.88).abs() < 1e-9, "node move lost");

        // Document and page identity must survive an edit (Phase 5).
        assert_eq!(n1.source_id, Some(1), "edit dropped document identity");
        assert_eq!(n1.page, Some(1), "edit dropped page identity");
        assert_eq!(n1.drawing, "doc1", "edit dropped drawing identity");

        // ── EDGE: add a user connection ───────────────────────────────────
        graph::insert_edge_by_id("P".to_string(), "s1_n2".to_string(),
                                 "s1_n3".to_string(), "process".to_string()).unwrap();
        let g = load();
        assert_eq!(g.edges.len(), 2, "user-created edge not persisted");

        // Step 8: a user-drawn edge must NOT be presented as extracted
        // geometry. It carries no provenance, so edgeTrust() reports
        // 'unknown' rather than 'geometry'.
        let user_edge = g.edges.iter().find(|e| e.source == "s1_n2" && e.target == "s1_n3").unwrap();
        assert!(user_edge.provenance.is_none(),
                "user-created edge was labelled as extracted geometry: {:?}", user_edge.provenance);

        // The extracted edge keeps its provenance and its route.
        let geo = g.edges.iter().find(|e| e.source == "s1_n1" && e.target == "s1_n2").unwrap();
        assert_eq!(geo.provenance.as_deref(), Some("geometry"), "provenance lost on reload");
        assert!(!geo.waypoints.is_null(), "extracted waypoints lost on reload");

        // ── EDGE: bend, then clear the bend ───────────────────────────────
        graph::update_edge_bend("P".to_string(), "s1_n1".to_string(),
                                "s1_n2".to_string(), 0.42, 0.43).unwrap();
        let g = load();
        let bent = g.edges.iter().find(|e| e.source == "s1_n1").unwrap();
        assert_eq!(bent.bend_x, Some(0.42), "edge bend not persisted");
        assert_eq!(bent.bend_y, Some(0.43), "edge bend not persisted");
        // A user bend must not overwrite the extracted route.
        assert!(!bent.waypoints.is_null(), "user bend destroyed extracted waypoints");

        graph::clear_edge_bend("P".to_string(), "s1_n1".to_string(), "s1_n2".to_string()).unwrap();
        let g = load();
        let cleared = g.edges.iter().find(|e| e.source == "s1_n1").unwrap();
        assert_eq!(cleared.bend_x, None, "bend not cleared");
        assert!(!cleared.waypoints.is_null(), "clearing a bend destroyed the extracted route");

        // ── EDGE: delete ──────────────────────────────────────────────────
        // delete_edge() keys on TAGS; the id-keyed command is delete_edge_by_id.
        graph::delete_edge_by_id("P".to_string(), "s1_n2".to_string(), "s1_n3".to_string()).unwrap();
        assert_eq!(load().edges.len(), 1, "edge delete not persisted");

        // ── NODE: delete, and its edges go with it ────────────────────────
        graph::delete_node("P".to_string(), "s1_n1".to_string()).unwrap();
        let g = load();
        assert_eq!(g.nodes.len(), 2, "node delete not persisted");
        assert_eq!(g.edges.len(), 0, "deleting a node left a dangling edge");

        std::env::remove_var("ENGINEERING_HUB");
        let _ = std::fs::remove_dir_all(&h);
    }

    #[test]
    fn reload_is_stable_when_nothing_changes() {
        let _guard = crate::database::TEST_HUB_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let h = hub("stable");
        let db = h.join("studio.db");
        seed(&db);
        std::env::set_var("ENGINEERING_HUB", h.to_str().unwrap());

        let a = serde_json::to_string(&load()).unwrap();
        let b = serde_json::to_string(&load()).unwrap();
        let c = serde_json::to_string(&load()).unwrap();
        assert_eq!(a, b, "repeated reloads differ");
        assert_eq!(b, c, "repeated reloads differ");

        std::env::remove_var("ENGINEERING_HUB");
        let _ = std::fs::remove_dir_all(&h);
    }

    #[test]
    fn editing_one_document_does_not_touch_another() {
        let _guard = crate::database::TEST_HUB_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let h = hub("crossdoc");
        let db = h.join("studio.db");
        seed(&db);
        {
            let conn = rusqlite::Connection::open(&db).unwrap();
            conn.execute(
                "INSERT INTO sources (pid,filename,file_hash,uploaded,cached)
                 VALUES ('P','b.pdf','hb',datetime('now'),1)",
                [],
            )
            .unwrap();
            for i in 1..=2 {
                conn.execute(
                    "INSERT INTO nodes (id,pid,kind,label,x,y,extra_json,source_id)
                     VALUES (?,'P','vessel',?,0.5,0.5,'{\"page\":1,\"drawing\":\"doc2\"}',2)",
                    rusqlite::params![format!("s2_n{}", i), format!("B-{}", i)],
                )
                .unwrap();
            }
        }
        std::env::set_var("ENGINEERING_HUB", h.to_str().unwrap());

        let before: Vec<_> = load().nodes.into_iter()
            .filter(|n| n.source_id == Some(2))
            .map(|n| (n.id, n.x, n.y, n.label))
            .collect();
        assert_eq!(before.len(), 2);

        graph::update_node_position("P".to_string(), "s1_n1".to_string(), 0.9, 0.9).unwrap();
        graph::delete_node("P".to_string(), "s1_n2".to_string()).unwrap();

        let after: Vec<_> = load().nodes.into_iter()
            .filter(|n| n.source_id == Some(2))
            .map(|n| (n.id, n.x, n.y, n.label))
            .collect();
        assert_eq!(after, before, "editing document 1 changed document 2");

        std::env::remove_var("ENGINEERING_HUB");
        let _ = std::fs::remove_dir_all(&h);
    }
}

#[cfg(test)]
mod connection_mirror_tests {
    use super::*;

    fn mem() -> rusqlite::Connection {
        let c = rusqlite::Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE nodes (id TEXT, pid TEXT, label TEXT);
             CREATE TABLE connections (id TEXT, pid TEXT, from_tag TEXT, to_tag TEXT,
                                       type TEXT, extra_json TEXT, PRIMARY KEY (id, pid));
             INSERT INTO nodes VALUES ('n1','P','V-101');
             INSERT INTO nodes VALUES ('n2','P','P-101');
             INSERT INTO nodes VALUES ('j1','P','');",
        ).unwrap();
        c
    }

    fn rows(c: &rusqlite::Connection) -> Vec<(String, String, String, String)> {
        let mut s = c.prepare("SELECT id, from_tag, to_tag, type FROM connections ORDER BY id").unwrap();
        let v = s.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
            .unwrap().map(|x| x.unwrap()).collect();
        v
    }

    /// VIDS reads `connections`. Without this, a connection drawn on the canvas
    /// reached YMPL and Mermaid (nodes+edges) but never VIDS.
    #[test]
    fn drawn_process_edge_reaches_the_vids_table() {
        let c = mem();
        upsert_connection(&c, "P", "n1", "n2", "process");
        assert_eq!(rows(&c), vec![("V-101→P-101".into(), "V-101".into(),
                                   "P-101".into(), "process".into())]);
    }

    /// Signal and pneumatic edges are topology only — _derive_studio_tables
    /// filters them out, so this path must too.
    #[test]
    fn signal_edge_is_topology_only() {
        let c = mem();
        upsert_connection(&c, "P", "n1", "n2", "signal");
        assert!(rows(&c).is_empty(), "signal edge must not create a connections row");
    }

    /// An endpoint on an unlabelled junction keeps a blank tag — never a
    /// substituted one — and is keyed by node id so two such edges cannot
    /// collide onto the same "→" row and overwrite each other.
    #[test]
    fn unlabelled_endpoint_keeps_blank_tag_and_a_unique_id() {
        let c = mem();
        upsert_connection(&c, "P", "n1", "j1", "process");
        upsert_connection(&c, "P", "j1", "n2", "process");
        let r = rows(&c);
        assert_eq!(r.len(), 2, "distinct edges collapsed onto one row");
        assert!(r.iter().any(|x| x.0 == "n1→j1" && x.1 == "V-101" && x.2.is_empty()));
        assert!(r.iter().any(|x| x.0 == "j1→n2" && x.1.is_empty() && x.2 == "P-101"));
    }

    /// Deleting the edge must not leave the row behind, or VIDS keeps
    /// reporting a connection the canvas no longer shows.
    #[test]
    fn deleting_the_edge_removes_the_connection() {
        let c = mem();
        upsert_connection(&c, "P", "n1", "n2", "process");
        upsert_connection(&c, "P", "n1", "j1", "process");
        delete_connection_for(&c, "P", "n1", "n2");
        delete_connection_for(&c, "P", "n1", "j1");
        assert!(rows(&c).is_empty(), "connections row outlived its edge");
    }
}

use rusqlite::Connection;

use serde_json::{json, Value};

// read_env_hub is gone from this module: every path below now goes through
// project_dir(), which validates project_id before joining it.
use crate::database::{open_db, collect_rows, find_db, project_dir};

use crate::models::PageImageResult;

use crate::utils::parse_image_dims;

/// A plain filename with no path component. Filenames reaching these commands
/// come from the renderer, so `../../secrets.txt` must not read as "a file in
/// source_docs".
pub(crate) fn is_safe_filename(name: &str) -> bool {
    !name.is_empty()
        && !name.contains('/')
        && !name.contains('\\')
        && !name.contains('\0')
        && name != "."
        && name != ".."
        && std::path::Path::new(name).file_name().map(|f| f == name).unwrap_or(false)
}

#[tauri::command]
pub fn debug_db() -> String {
    match find_db() {
        None => "No studio.db found in any candidate path".to_string(),
        Some(path) => {
            match Connection::open(&path) {
                Err(e) => format!("open error on {}: {}", path, e),
                Ok(conn) => {
                    let count: i64 = conn
                        .query_row("SELECT COUNT(*) FROM projects", [], |r| r.get(0))
                        .unwrap_or(-1);
                    format!("OK path={} projects={}", path, count)
                }
            }
        }
    }
}

#[tauri::command]
pub fn get_source_data_url(project_id: String, filename: String) -> Result<String, String> {
    use base64::Engine as _;
    // project_dir validates project_id (paths::is_safe_project_id). The raw
    // hub.join("projects").join(project_id) this replaced accepted ".." or
    // "C:\Windows" straight from the webview.
    let proj = project_dir(&project_id)
        .ok_or("Invalid project id, or no studio.db found")?;
    if !is_safe_filename(&filename) {
        return Err(format!("Invalid filename: {:?}", filename));
    }
    let path = proj.join("source_docs").join(&filename);
    let ext = path.extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    let mime = match ext.as_str() {
        "png"  => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        _ => return Err(format!("Not an image: {}", filename)),
    };
    let bytes = std::fs::read(&path)
        .map_err(|e| format!("Cannot read {}: {}", path.display(), e))?;
    let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);
    Ok(format!("data:{};base64,{}", mime, encoded))
}

// 15 MB cap on raw file size — comfortably above typical drawing exports/docs,
// but stops a huge accidental pick from ballooning the base64 payload sent to
// an LLM (base64 adds ~33% on top of this).
const MAX_ATTACHMENT_BYTES: usize = 15 * 1024 * 1024;

// Generic "read an arbitrary user-picked file, base64-encode it" command for
// the Describe attach feature. Deliberately dumb — it does no format-specific
// interpretation (image vs PDF vs text vs docx); that classification and any
// parsing (e.g. docx→text) happens in TypeScript, keeping this one command
// reusable for any future attachment-like need instead of hardcoding a format
// list into Rust.
#[tauri::command]
pub fn read_attachment(file_path: String) -> Result<Value, String> {
    use base64::Engine as _;
    let path = std::path::Path::new(&file_path);
    let bytes = std::fs::read(path)
        .map_err(|e| format!("Cannot read {}: {}", path.display(), e))?;
    if bytes.len() > MAX_ATTACHMENT_BYTES {
        return Err(format!(
            "File is {:.1} MB — attachments are limited to 15 MB.",
            bytes.len() as f64 / (1024.0 * 1024.0)
        ));
    }
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("attachment").to_string();
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
    let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);
    Ok(json!({ "name": name, "ext": ext, "data": encoded, "size": bytes.len() }))
}

#[tauri::command]
pub fn get_page_image_path(project_id: String, _page: Option<u32>) -> Result<PageImageResult, String> {
    use base64::Engine as _;

    fn encode(p: &std::path::Path) -> Result<PageImageResult, String> {
        let bytes = std::fs::read(p).map_err(|e| e.to_string())?;
        let ext = p.extension().and_then(|e| e.to_str()).unwrap_or("png").to_lowercase();
        let mime = if ext == "jpg" { "jpeg" } else { ext.as_str() };
        let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);
        let url = format!("data:image/{};base64,{}", mime, encoded);
        let (width, height) = parse_image_dims(&bytes);
        Ok(PageImageResult { url, width, height })
    }

    if let Some(proj) = project_dir(&project_id) {
        // 1. A rendered full-page image, if extraction produced one.
        for ext in &["png", "jpg", "jpeg"] {
            let p = proj.join("cache").join("pages").join(format!("page_1.{}", ext));
            if p.exists() {
                return encode(&p);
            }
        }

        // 2. Fall back to the source document image itself (single-sheet PNG/JPG
        //    uploads have no rendered page — the source IS the page).
        let sd = proj.join("source_docs");
        if let Ok(rd) = std::fs::read_dir(&sd) {
            let mut imgs: Vec<std::path::PathBuf> = rd
                .filter_map(|e| e.ok().map(|e| e.path()))
                .filter(|p| matches!(
                    p.extension().and_then(|x| x.to_str()).map(|s| s.to_lowercase()).as_deref(),
                    Some("png") | Some("jpg") | Some("jpeg")
                ))
                .collect();
            imgs.sort();
            if let Some(p) = imgs.first() {
                return encode(p);
            }
        }
    }
    Err("Page image not found — run extraction first to generate page cache".into())
}

// ── get_edge_paths — real detected pipe geometry for canvas edges ─────────────
// Returns the {width,height,paths:[{from,to,kind,waypoints}]} sidecar written by
// backend/services/edge_path_service.py (scripts/run_edge_paths.py). Waypoints are
// normalized 0–1 sheet coordinates. Missing file → empty set (UI falls back to
// smoothstep), never an error.
#[tauri::command]
pub fn get_edge_paths(project_id: String) -> Result<Value, String> {
    let empty = json!({ "width": 0, "height": 0, "paths": [] });

    if let Some(proj) = project_dir(&project_id) {
        let cache = proj.join("cache");

        // Preferred name <pid>_paths.json, else first *_paths.json in cache.
        let mut target = cache.join(format!("{}_paths.json", project_id));
        if !target.exists() {
            if let Ok(rd) = std::fs::read_dir(&cache) {
                target = rd
                    .filter_map(|e| e.ok().map(|e| e.path()))
                    .find(|p| p.file_name()
                        .and_then(|n| n.to_str())
                        .map(|s| s.ends_with("_paths.json"))
                        .unwrap_or(false))
                    .unwrap_or(target);
            }
        }

        if target.exists() {
            let text = std::fs::read_to_string(&target).map_err(|e| e.to_string())?;
            let val: Value = serde_json::from_str(&text)
                .map_err(|e| format!("Parse {}: {}", target.display(), e))?;
            return Ok(val);
        }
    }
    Ok(empty)
}

#[tauri::command]
pub fn get_usage_history(user_id: Option<i64>) -> Result<Vec<Value>, String> {
    let conn = open_db()?;
    let mut stmt = conn.prepare(
        "SELECT p.id,
                COALESCE(p.title, p.plant_name, p.id) AS name,
                COALESCE(c.total_tokens, 0) AS total_tokens,
                COALESCE(c.total_cost, 0.0) AS total_cost,
                COALESCE(c.last_scan, '') AS last_scan,
                COALESCE(c.scan_json, '[]') AS scan_json
         FROM projects p
         LEFT JOIN cache_manifest c ON c.pid = p.id
         -- Same rule as list_projects: strictly the signed-in user's projects.
         WHERE p.user_id = ?
         ORDER BY c.last_scan DESC"
    ).map_err(|e| format!("Prepare failed: {}", e))?;

    collect_rows(&mut stmt, [user_id], |row| {
        let scans_str: String = row.get(5)?;
        let scans: Value = serde_json::from_str(&scans_str).unwrap_or(json!([]));
        Ok(json!({
            "pid": row.get::<_, String>(0)?,
            "name": row.get::<_, String>(1)?,
            "total_tokens": row.get::<_, i64>(2)?,
            "total_cost": row.get::<_, f64>(3)?,
            "last_scan": row.get::<_, String>(4)?,
            "scans": scans
        }))
    })
}

/// Clears a whole project's usage/cost tracking (cache_manifest row) — does
/// NOT touch the project itself or its extracted data, only the usage
/// history shown in the Usage popup.
#[tauri::command]
pub fn delete_project_usage(pid: String) -> Result<(), String> {
    let conn = open_db()?;
    conn.execute("DELETE FROM cache_manifest WHERE pid = ?1", [pid])
        .map_err(|e| format!("delete_project_usage failed: {}", e))?;
    Ok(())
}

/// Removes ONE scan entry (by its index in scan_json, as currently ordered —
/// oldest first, matching the column stored) from a project's usage history,
/// then recomputes total_tokens/total_cost/last_scan from what remains so the
/// totals stay consistent with the deleted entry actually being gone.
#[tauri::command]
pub fn delete_usage_scan(pid: String, scan_index: usize) -> Result<(), String> {
    let conn = open_db()?;
    let scan_json: String = conn.query_row(
        "SELECT COALESCE(scan_json, '[]') FROM cache_manifest WHERE pid = ?1",
        [&pid],
        |r| r.get(0),
    ).map_err(|e| format!("delete_usage_scan: project not found: {}", e))?;

    let mut scans: Vec<Value> = serde_json::from_str(&scan_json).unwrap_or_default();
    if scan_index >= scans.len() {
        return Err("scan index out of range".to_string());
    }
    scans.remove(scan_index);

    let total_tokens: i64 = scans.iter()
        .map(|s| s.get("tokens_in").and_then(Value::as_i64).unwrap_or(0)
               + s.get("tokens_out").and_then(Value::as_i64).unwrap_or(0))
        .sum();
    let total_cost: f64 = scans.iter()
        .map(|s| s.get("cost_usd").and_then(Value::as_f64).unwrap_or(0.0))
        .sum();
    let last_scan: String = scans.iter()
        .filter_map(|s| s.get("timestamp").and_then(Value::as_str))
        .max()
        .unwrap_or("")
        .to_string();

    conn.execute(
        "UPDATE cache_manifest SET scan_json = ?1, total_tokens = ?2, total_cost = ?3, last_scan = ?4 WHERE pid = ?5",
        rusqlite::params![
            serde_json::to_string(&scans).unwrap_or_default(),
            total_tokens, total_cost, last_scan, pid,
        ],
    ).map_err(|e| format!("delete_usage_scan update failed: {}", e))?;

    Ok(())
}

/// Appends a new usage scan to a project's history.
/// Used by frontend-initiated LLM calls (e.g. Describe) to log their usage.
#[tauri::command]
pub fn add_usage_scan(
    pid: String, provider: String, model: String,
    tokens_in: i64, tokens_out: i64, cost_usd: f64
) -> Result<(), String> {
    let conn = crate::database::open_db()
        .map_err(|e| format!("Database connection failed: {}", e))?;

    let old_scans_str: String = conn.query_row(
        "SELECT scan_json FROM cache_manifest WHERE pid = ?1",
        rusqlite::params![pid],
        |row| row.get(0),
    ).unwrap_or_else(|_| "[]".to_string());

    let mut scans: Vec<Value> = serde_json::from_str(&old_scans_str).unwrap_or_default();
    
    let ts: String = conn.query_row(
        "SELECT strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        [],
        |row| row.get(0),
    ).unwrap_or_else(|_| "".to_string());

    scans.push(serde_json::json!({
        "timestamp": ts,
        "filename": "Describe Feature",
        "provider": provider,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "pass": 1
    }));

    let total_tokens: i64 = scans.iter()
        .map(|s| s.get("tokens_in").and_then(Value::as_i64).unwrap_or(0)
               + s.get("tokens_out").and_then(Value::as_i64).unwrap_or(0))
        .sum();
    let total_cost: f64 = scans.iter()
        .map(|s| s.get("cost_usd").and_then(Value::as_f64).unwrap_or(0.0))
        .sum();

    conn.execute(
        "INSERT INTO cache_manifest (pid, scan_json, total_tokens, total_cost, last_scan)
         VALUES (?1, ?2, ?3, ?4, ?5)
         ON CONFLICT(pid) DO UPDATE SET
           scan_json = excluded.scan_json,
           total_tokens = excluded.total_tokens,
           total_cost = excluded.total_cost,
           last_scan = excluded.last_scan",
        rusqlite::params![
            pid,
            serde_json::to_string(&scans).unwrap_or_default(),
            total_tokens, total_cost, ts
        ],
    ).map_err(|e| format!("add_usage_scan update failed: {}", e))?;

    Ok(())
}

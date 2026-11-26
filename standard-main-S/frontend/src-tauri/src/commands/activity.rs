// Persists the extraction activity feed (Initialising → Symbols → … →
// Complete) to the DB so it survives app restarts and is visible across
// machines sharing the same EngineeringHub — unlike localStorage, which is
// per-machine and was the previous approach. One row per (pid, stage): a new
// event for a stage that already has a row updates it in place, mirroring
// the frontend's own mergeEntry() semantics for a running extraction.

use serde::Deserialize;
use serde_json::{json, Value};

use crate::database::{collect_rows, open_db};

// camelCase to match the JS side's natural object shape (projectId, startedAt,
// durationMs) — Tauri's arg-name camelCasing only applies to command
// parameter NAMES, not to the fields of a struct passed as one JSON param.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ActivityEntryInput {
    pub project_id: String,
    pub stage: String,
    pub label: String,
    pub detail: String,
    pub status: String,
    pub started_at: i64,
    pub duration_ms: Option<i64>,
    pub indent: bool,
}

/// Drop rows older than 30 days. Called opportunistically on every read/write
/// instead of a scheduled job — this table is small (a handful of rows per
/// project) so a DELETE on each call is cheap and needs no extra machinery.
fn prune_old(conn: &rusqlite::Connection) {
    let _ = conn.execute(
        "DELETE FROM activity_log WHERE updated_at < datetime('now', '-30 days')",
        [],
    );
}

#[tauri::command]
pub fn save_activity_entry(entry: ActivityEntryInput) -> Result<(), String> {
    let conn = open_db()?;
    prune_old(&conn);
    conn.execute(
        "INSERT INTO activity_log (pid, stage, label, detail, status, started_at, duration_ms, indent, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, datetime('now'))
         ON CONFLICT(pid, stage) DO UPDATE SET
           label       = excluded.label,
           detail      = excluded.detail,
           status      = excluded.status,
           started_at  = excluded.started_at,
           duration_ms = excluded.duration_ms,
           indent      = excluded.indent,
           updated_at  = datetime('now')",
        rusqlite::params![
            entry.project_id,
            entry.stage,
            entry.label,
            entry.detail,
            entry.status,
            entry.started_at,
            entry.duration_ms,
            entry.indent as i64,
        ],
    )
    .map_err(|e| format!("save_activity_entry failed: {}", e))?;
    Ok(())
}

/// All persisted activity rows across every project, newest first. The
/// frontend groups these back into byProject[pid].log on startup.
#[tauri::command]
pub fn get_activity_log() -> Result<Value, String> {
    let conn = open_db()?;
    prune_old(&conn);
    let mut stmt = conn
        .prepare(
            "SELECT pid, stage, label, detail, status, started_at, duration_ms, indent
             FROM activity_log ORDER BY started_at DESC",
        )
        .map_err(|e| format!("Prepare activity_log: {}", e))?;
    let rows = collect_rows(&mut stmt, [], |row| {
        Ok(json!({
            "pid":        row.get::<_, String>(0)?,
            "stage":      row.get::<_, String>(1)?,
            "label":      row.get::<_, String>(2)?,
            "detail":     row.get::<_, String>(3)?,
            "status":     row.get::<_, String>(4)?,
            "startedAt":  row.get::<_, i64>(5)?,
            "durationMs": row.get::<_, Option<i64>>(6)?,
            "indent":     row.get::<_, i64>(7)? != 0,
        }))
    })?;
    Ok(json!(rows))
}

/// Clears one project's persisted log — called when a new extraction starts,
/// so a fresh run doesn't show stale stage rows left over from a prior run
/// that had more/different steps.
#[tauri::command]
pub fn clear_activity_log(project_id: String) -> Result<(), String> {
    let conn = open_db()?;
    conn.execute("DELETE FROM activity_log WHERE pid = ?1", [project_id])
        .map_err(|e| format!("clear_activity_log failed: {}", e))?;
    Ok(())
}

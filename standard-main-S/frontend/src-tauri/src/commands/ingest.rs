use serde_json::{json, Value};

use crate::database::{open_db, project_dir, collect_rows};

#[tauri::command]
pub fn get_sources(project_id: String) -> Result<Vec<Value>, String> {
    let conn = open_db()?;
    let mut stmt = conn.prepare(
        "SELECT id, filename, COALESCE(file_hash,'') AS file_hash,
                COALESCE(uploaded,'') AS uploaded, cached
         FROM sources
         WHERE pid = ?
         ORDER BY uploaded DESC"
    ).map_err(|e| format!("Prepare failed: {}", e))?;

    collect_rows(&mut stmt, [project_id.as_str()], |row| {
        let cached: i64 = row.get(4)?;
        Ok(json!({
            "id":        row.get::<_, i64>(0)?,
            "filename":  row.get::<_, String>(1)?,
            "file_hash": row.get::<_, String>(2)?,
            "uploaded":  row.get::<_, String>(3)?,
            "cached":    cached != 0,
            "status":    if cached != 0 { "complete" } else { "uploaded" }
        }))
    })
}

#[tauri::command]
pub fn native_upload_file(project_id: String, file_path: String) -> Result<Value, String> {
    use sha2::{Digest, Sha256};

    let src = std::path::Path::new(&file_path);

    // Read file bytes
    let bytes = std::fs::read(src)
        .map_err(|e| format!("Cannot read file: {}", e))?;

    // SHA-256 hash for dedup
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let hash_hex = format!("{:x}", hasher.finalize());

    // Resolve source_docs directory
    let source_docs = project_dir(&project_id)
        .ok_or("No studio.db found")?
        .join("source_docs");
    std::fs::create_dir_all(&source_docs)
        .map_err(|e| format!("Cannot create source_docs/: {}", e))?;

    // Filename
    let filename = src
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or("Invalid file path — no filename component")?
        .to_string();

    // Copy PDF into source_docs/
    let dest = source_docs.join(&filename);
    std::fs::copy(src, &dest)
        .map_err(|e| format!("Cannot copy file: {}", e))?;

    let conn = open_db()?;

    // Dedup by hash — return existing row if same file uploaded before
    let existing: Option<i64> = conn
        .query_row(
            "SELECT id FROM sources WHERE pid=? AND file_hash=?",
            [project_id.as_str(), hash_hex.as_str()],
            |r| r.get(0),
        )
        .ok();

    if let Some(id) = existing {
        return Ok(json!({
            "success":   true,
            "filename":  filename,
            "source_id": id,
            "duplicate": true,
        }));
    }

    // Insert new sources row; let SQLite fill in the timestamp
    conn.execute(
        "INSERT INTO sources (pid, filename, file_hash, uploaded, cached)
         VALUES (?, ?, ?, datetime('now'), 0)",
        [project_id.as_str(), filename.as_str(), hash_hex.as_str()],
    ).map_err(|e| format!("INSERT sources failed: {}", e))?;

    let source_id = conn.last_insert_rowid();
    Ok(json!({
        "success":   true,
        "filename":  filename,
        "source_id": source_id,
        "duplicate": false,
    }))
}

// Shared helper — build multipart body and POST to Flask parse/image.
// Uses a 5-minute read timeout so extraction can complete before ureq gives up.
fn send_pdf_to_flask(project_id: &str, filename: &str, file_bytes: &[u8]) -> Result<Value, String> {
    let url = format!(
        "http://localhost:8000/api/projects/{}/parse/image",
        project_id
    );

    let boundary = "plantsketch_upload_boundary_42";
    let mut body: Vec<u8> = Vec::new();
    body.extend_from_slice(format!("--{}\r\n", boundary).as_bytes());
    body.extend_from_slice(
        format!(
            "Content-Disposition: form-data; name=\"file\"; filename=\"{}\"\r\n",
            filename
        )
        .as_bytes(),
    );
    body.extend_from_slice(b"Content-Type: application/pdf\r\n\r\n");
    body.extend_from_slice(file_bytes);
    body.extend_from_slice(format!("\r\n--{}--\r\n", boundary).as_bytes());

    let content_type = format!("multipart/form-data; boundary={}", boundary);

    // Long timeout: Claude extraction can take 3-5 minutes for large P&IDs
    let agent = ureq::AgentBuilder::new()
        .timeout_read(std::time::Duration::from_secs(360))
        .timeout_write(std::time::Duration::from_secs(60))
        .build();

    let resp = agent
        .post(&url)
        .set("Content-Type", &content_type)
        .send_bytes(&body)
        .map_err(|e| {
            let s = e.to_string();
            if s.contains("Connection refused") || s.contains("tcp connect") {
                "Studio server is not running — start it: cd studio && python main.py".to_string()
            } else {
                format!("Upload failed: {}", s)
            }
        })?;

    if resp.status() != 200 {
        let status = resp.status();
        let err_body = resp.into_string().unwrap_or_default();
        return Err(format!("Flask returned HTTP {}: {}", status, &err_body[..err_body.len().min(200)]));
    }

    let data: Value = resp
        .into_json()
        .map_err(|e| format!("JSON parse error: {}", e))?;

    if let Some(err) = data.get("error").and_then(|v| v.as_str()) {
        return Err(format!("Extraction error: {}", err));
    }

    let node_count  = data.get("ympl_doc").and_then(|d| d.get("nodes")).and_then(|n| n.as_array()).map(|a| a.len()).unwrap_or(0);
    let instr_count = data.get("instruments").and_then(|i| i.as_object()).map(|o| o.len()).unwrap_or(0);
    let equip_count = data.get("equipment").and_then(|e| e.as_object()).map(|o| o.len()).unwrap_or(0);
    let from_cache  = data.get("cached").and_then(|c| c.as_bool()).unwrap_or(false);
    let warnings: Vec<String> = data.get("warnings").and_then(|w| w.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
        .unwrap_or_default();

    Ok(json!({
        "ok":          true,
        "nodes":       node_count,
        "instruments": instr_count,
        "equipment":   equip_count,
        "from_cache":  from_cache,
        "warnings":    warnings
    }))
}

#[tauri::command]
pub fn upload_pdf(project_id: String, file_path: String) -> Result<Value, String> {
    let file_bytes = std::fs::read(&file_path)
        .map_err(|e| format!("Cannot read '{}': {}", file_path, e))?;
    let filename = std::path::Path::new(&file_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("source.pdf")
        .to_string();
    let result = send_pdf_to_flask(&project_id, &filename, &file_bytes)?;
    // Record in sources table so get_sources picks it up immediately
    if let Ok(conn) = open_db() {
        let _ = conn.execute(
            "INSERT INTO sources (pid, filename, uploaded, cached)
             SELECT ?, ?, datetime('now'), 1
             WHERE NOT EXISTS (SELECT 1 FROM sources WHERE pid = ? AND filename = ?)",
            rusqlite::params![project_id, filename, project_id, filename],
        );
    }
    Ok(result)
}

// Re-run extraction on an already-uploaded source file.
// The file lives at {hub}/projects/{pid}/source_docs/{filename}.
#[tauri::command]
pub fn reextract_source(project_id: String, filename: String) -> Result<Value, String> {
    let file_path = project_dir(&project_id)
        .ok_or_else(|| "No studio.db found".to_string())?
        .join("source_docs")
        .join(&filename);
    let file_bytes = std::fs::read(&file_path)
        .map_err(|e| format!("Cannot read '{}': {}", file_path.display(), e))?;
    send_pdf_to_flask(&project_id, &filename, &file_bytes)
}

/// Remove one uploaded document and everything extracted from it (Phase 5).
///
/// Only rows carrying this `source_id` are touched, so the project's other
/// documents are untouched by construction rather than by filtering. Edges are
/// deleted both by their own source_id and by endpoint, because an edge whose
/// endpoints are being removed cannot survive regardless of which document
/// recorded it — leaving it behind is exactly the orphan row Step 12 forbids.
///
/// Legacy rows (source_id IS NULL) are never matched by this, so deleting a
/// document from a migrated project cannot take pre-migration data with it.
#[tauri::command]
pub fn delete_source(project_id: String, source_id: i64) -> Result<serde_json::Value, String> {
    let mut conn = open_db()?;

    let filename: String = conn
        .query_row(
            "SELECT filename FROM sources WHERE id = ? AND pid = ?",
            rusqlite::params![source_id, project_id.as_str()],
            |r| r.get(0),
        )
        .map_err(|e| format!("Source {} not found in {}: {}", source_id, project_id, e))?;

    let tx = conn.transaction().map_err(|e| e.to_string())?;

    // Edges first: they reference nodes, so removing them before the nodes
    // means the database is never in a state with dangling endpoints.
    let edges_removed = tx
        .execute(
            "DELETE FROM edges
              WHERE pid = ?
                AND (source_id = ?
                     OR from_id IN (SELECT id FROM nodes WHERE pid = ? AND source_id = ?)
                     OR to_id   IN (SELECT id FROM nodes WHERE pid = ? AND source_id = ?))",
            rusqlite::params![
                project_id.as_str(), source_id,
                project_id.as_str(), source_id,
                project_id.as_str(), source_id
            ],
        )
        .map_err(|e| format!("Delete edges: {}", e))?;

    // Canvas positions and review rows are keyed by node id, so they have to go
    // with the nodes or they become unreachable rows that a later document
    // could accidentally inherit by reusing an id.
    for (tbl, col) in [("canvas_positions", "node_id"), ("proposals", "node_id")] {
        let sql = format!(
            "DELETE FROM {} WHERE pid = ? AND {} IN              (SELECT id FROM nodes WHERE pid = ? AND source_id = ?)",
            tbl, col
        );
        if let Err(e) = tx.execute(&sql, rusqlite::params![project_id.as_str(), project_id.as_str(), source_id]) {
            if !e.to_string().contains("no such table") {
                return Err(format!("Delete {}: {}", tbl, e));
            }
        }
    }

    let nodes_removed = tx
        .execute(
            "DELETE FROM nodes WHERE pid = ? AND source_id = ?",
            rusqlite::params![project_id.as_str(), source_id],
        )
        .map_err(|e| format!("Delete nodes: {}", e))?;

    tx.execute(
        "DELETE FROM sources WHERE id = ? AND pid = ?",
        rusqlite::params![source_id, project_id.as_str()],
    )
    .map_err(|e| format!("Delete source row: {}", e))?;

    tx.commit().map_err(|e| e.to_string())?;

    // The PDF itself is only removed once the rows are committed, so a failed
    // transaction cannot leave the project pointing at a file that is gone.
    if let Some(dir) = crate::database::project_dir(&project_id) {
        let _ = std::fs::remove_file(dir.join("source_docs").join(&filename));
    }

    Ok(serde_json::json!({
        "success":       true,
        "filename":      filename,
        "nodes_removed": nodes_removed,
        "edges_removed": edges_removed,
    }))
}

#[cfg(test)]
mod phase6_lifecycle_tests {
    //! Phase 6 Step 6 — the mandatory multi-document lifecycle, run against the
    //! REAL delete_source command rather than a mirror of its SQL.
    //! ENGINEERING_HUB is pointed at a temp hub so open_db() resolves there.
    //!
    //! Sequence: open A, open B, reload A, reload B, re-extract A, reload B,
    //! delete A, reload B. Document B must be identical at every step.

    type Row = (String, Option<i64>, String);

    const PREFIX: &str = "enstudio_p6";

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

    fn seed(conn: &rusqlite::Connection) {
        conn.execute_batch(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT, status TEXT);
             CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT,
                 filename TEXT, file_hash TEXT, uploaded TEXT, cached INTEGER);
             CREATE TABLE nodes (id TEXT, pid TEXT, kind TEXT, kind_detail TEXT, label TEXT,
                 area TEXT, x REAL, y REAL, extra_json TEXT, source_id INTEGER,
                 PRIMARY KEY (id, pid));
             CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, from_id TEXT,
                 to_id TEXT, kind TEXT, label TEXT, extra_json TEXT, source_id INTEGER);
             CREATE TABLE canvas_positions (pid TEXT, node_id TEXT, x REAL, y REAL,
                 PRIMARY KEY (pid, node_id));
             CREATE TABLE proposals (pid TEXT, node_id TEXT, type TEXT, original TEXT,
                 proposed TEXT, confidence REAL, method TEXT, review_state TEXT,
                 extra_json TEXT, PRIMARY KEY (pid, node_id, type));
             INSERT INTO projects VALUES ('P','P','done');",
        )
        .unwrap();
    }

    /// Write one document exactly as the Phase 5 extraction path does:
    /// s{src}_p{page}_{local} ids, source_id on every row.
    fn write_doc(conn: &rusqlite::Connection, sid: i64, locals: &[&str], pages: i64) {
        conn.execute("DELETE FROM edges WHERE pid='P' AND source_id=?", [sid]).unwrap();
        conn.execute("DELETE FROM nodes WHERE pid='P' AND source_id=?", [sid]).unwrap();
        for pg in 1..=pages {
            let px = format!("s{}_p{}_", sid, pg);
            for l in locals {
                let extra = format!("{{\"page\":{},\"drawing\":\"doc{}_p{}\"}}", pg, sid, pg);
                conn.execute(
                    "INSERT INTO nodes (id,pid,kind,label,x,y,extra_json,source_id)
                     VALUES (?,'P','vessel',?,0.5,0.5,?,?)",
                    rusqlite::params![format!("{}{}", px, l), l.to_uppercase(), extra, sid],
                )
                .unwrap();
            }
            conn.execute(
                "INSERT INTO edges (pid,from_id,to_id,kind,source_id) VALUES ('P',?,?,'process',?)",
                rusqlite::params![format!("{}n1", px), format!("{}n2", px), sid],
            )
            .unwrap();
        }
    }

    /// "Reload" — read the document back the way get_graph does.
    fn reload(path: &std::path::Path, sid: i64) -> Vec<Row> {
        let conn = rusqlite::Connection::open(path).unwrap();
        let mut st = conn
            .prepare(
                "SELECT id, source_id, COALESCE(json_extract(extra_json,'$.drawing'),'')
                 FROM nodes WHERE pid='P' AND source_id=? ORDER BY id",
            )
            .unwrap();
        let v = st
            .query_map([sid], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();
        v
    }

    fn edge_count(path: &std::path::Path, sid: i64) -> i64 {
        rusqlite::Connection::open(path)
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM edges WHERE pid='P' AND source_id=?",
                [sid],
                |r| r.get(0),
            )
            .unwrap()
    }

    #[test]
    fn multi_document_lifecycle_never_disturbs_the_other_document() {
        let _guard = crate::database::TEST_HUB_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let h = hub("lifecycle");
        let db = h.join("studio.db");
        {
            let conn = rusqlite::Connection::open(&db).unwrap();
            seed(&conn);
            // Same filename, same local ids, same page numbers — the collision case.
            conn.execute(
                "INSERT INTO sources (pid,filename,file_hash,uploaded,cached)
                 VALUES ('P','sheet.pdf','hash-A',datetime('now'),1)",
                [],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO sources (pid,filename,file_hash,uploaded,cached)
                 VALUES ('P','sheet.pdf','hash-B',datetime('now'),1)",
                [],
            )
            .unwrap();
            write_doc(&conn, 1, &["n1", "n2", "gj_0"], 2);
            write_doc(&conn, 2, &["n1", "n2", "gj_0"], 2);
        }
        std::env::set_var("ENGINEERING_HUB", h.to_str().unwrap());

        // 1/2. open A, open B
        let a0 = reload(&db, 1);
        let b0 = reload(&db, 2);
        assert_eq!(a0.len(), 6, "document A loads");
        assert_eq!(b0.len(), 6, "document B loads");
        assert_ne!(a0[0].0, b0[0].0, "documents must not share node ids");

        // 3/4. reload A, reload B — stable
        assert_eq!(reload(&db, 1), a0);
        assert_eq!(reload(&db, 2), b0);

        // 5. re-extract A (finds an extra symbol this time)
        {
            let conn = rusqlite::Connection::open(&db).unwrap();
            write_doc(&conn, 1, &["n1", "n2", "gj_0", "n3"], 2);
        }
        assert_eq!(reload(&db, 1).len(), 8, "re-extraction replaces A's own rows");

        // 6. reload B — MUST be unchanged
        assert_eq!(reload(&db, 2), b0, "re-extracting A changed B");
        assert_eq!(edge_count(&db, 2), 2, "re-extracting A changed B's edges");

        // 7. delete A — through the REAL command
        let out = super::delete_source("P".to_string(), 1).expect("delete_source failed");
        assert_eq!(out["nodes_removed"], 8);

        // 8. reload B — MUST still be unchanged
        assert_eq!(reload(&db, 2), b0, "deleting A changed B");
        assert_eq!(edge_count(&db, 2), 2, "deleting A changed B's edges");
        assert!(reload(&db, 1).is_empty(), "A must be gone");

        // No orphans left behind.
        let conn = rusqlite::Connection::open(&db).unwrap();
        let orphans: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM edges e WHERE e.pid='P' AND (
                   NOT EXISTS (SELECT 1 FROM nodes n WHERE n.pid=e.pid AND n.id=e.from_id) OR
                   NOT EXISTS (SELECT 1 FROM nodes n WHERE n.pid=e.pid AND n.id=e.to_id))",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(orphans, 0, "delete_source left orphan edges");

        std::env::remove_var("ENGINEERING_HUB");
        let _ = std::fs::remove_dir_all(&h);
    }

    #[test]
    fn delete_source_refuses_a_document_from_another_project() {
        let _guard = crate::database::TEST_HUB_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let h = hub("isolation");
        let db = h.join("studio.db");
        {
            let conn = rusqlite::Connection::open(&db).unwrap();
            seed(&conn);
            conn.execute("INSERT INTO projects VALUES ('Q','Q','done')", []).unwrap();
            conn.execute(
                "INSERT INTO sources (pid,filename,file_hash,uploaded,cached)
                 VALUES ('Q','q.pdf','hash-Q',datetime('now'),1)",
                [],
            )
            .unwrap();
            write_doc(&conn, 1, &["n1", "n2"], 1);
        }
        std::env::set_var("ENGINEERING_HUB", h.to_str().unwrap());

        // Source 1 belongs to Q; deleting it "from" P must fail, not wipe rows.
        let res = super::delete_source("P".to_string(), 1);
        assert!(res.is_err(), "delete_source must not act across projects");

        let conn = rusqlite::Connection::open(&db).unwrap();
        let left: i64 = conn
            .query_row("SELECT COUNT(*) FROM nodes WHERE pid='P'", [], |r| r.get(0))
            .unwrap();
        assert_eq!(left, 2, "a refused delete must not remove anything");

        std::env::remove_var("ENGINEERING_HUB");
        let _ = std::fs::remove_dir_all(&h);
    }
}

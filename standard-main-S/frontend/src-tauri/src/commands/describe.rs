use serde_json::{json, Value};

use crate::database::{open_db, collect_rows, find_python, find_cli_and_hub,
                      find_studio_script};

#[tauri::command]
pub fn list_describe_sessions(project_id: String) -> Result<Value, String> {
    let conn = open_db()?;
    let mut stmt = conn.prepare(
        "SELECT s.id, COALESCE(s.title, 'New chat'), s.updated_at,
                (SELECT COUNT(*) FROM describe_messages m WHERE m.session_id = s.id)
         FROM describe_sessions s
         WHERE s.pid = ?
         ORDER BY s.updated_at DESC, s.id DESC"
    ).map_err(|e| format!("Prepare sessions: {}", e))?;
    let rows = collect_rows(&mut stmt, [project_id.as_str()], |row| {
        Ok(json!({
            "id":           row.get::<_, i64>(0)?,
            "title":        row.get::<_, String>(1)?,
            "updated_at":   row.get::<_, String>(2)?,
            "message_count":row.get::<_, i64>(3)?,
        }))
    })?;
    Ok(json!(rows))
}

#[tauri::command]
pub fn create_describe_session(project_id: String) -> Result<Value, String> {
    let conn = open_db()?;
    conn.execute(
        "INSERT INTO describe_sessions (pid, title, created_at, updated_at)
         VALUES (?, NULL, datetime('now'), datetime('now'))",
        [project_id.as_str()],
    ).map_err(|e| format!("Create session failed: {}", e))?;
    Ok(json!({ "id": conn.last_insert_rowid() }))
}

#[tauri::command]
pub fn get_describe_messages(session_id: i64) -> Result<Value, String> {
    let conn = open_db()?;
    let mut stmt = conn.prepare(
        "SELECT id, role, display, api_content, nodes_added, edges_added, nodes_updated,
                pending_deletes, delete_resolution, nodes_deleted, is_error
         FROM describe_messages WHERE session_id = ? ORDER BY id ASC"
    ).map_err(|e| format!("Prepare messages: {}", e))?;
    let rows = collect_rows(&mut stmt, [session_id], |row| {
        Ok(json!({
            "id":               row.get::<_, i64>(0)?,
            "role":             row.get::<_, String>(1)?,
            "display":          row.get::<_, String>(2)?,
            "api_content":      row.get::<_, String>(3)?,
            "nodes_added":      row.get::<_, i64>(4)?,
            "edges_added":      row.get::<_, i64>(5)?,
            "nodes_updated":    row.get::<_, i64>(6)?,
            "pending_deletes":  row.get::<_, Option<String>>(7)?,
            "delete_resolution":row.get::<_, Option<String>>(8)?,
            "nodes_deleted":    row.get::<_, i64>(9)?,
            "is_error":         row.get::<_, i64>(10)?,
        }))
    })?;
    Ok(json!(rows))
}

#[tauri::command]
pub fn save_describe_message(
    session_id: i64,
    project_id: String,
    role: String,
    display: String,
    api_content: String,
    nodes_added: i64,
    edges_added: i64,
    nodes_updated: i64,
    pending_deletes: Option<String>,
    is_error: bool,
) -> Result<Value, String> {
    let conn = open_db()?;
    conn.execute(
        "INSERT INTO describe_messages
           (session_id, pid, role, display, api_content, nodes_added, edges_added,
            nodes_updated, pending_deletes, is_error, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        rusqlite::params![
            session_id, project_id, role, display, api_content,
            nodes_added, edges_added, nodes_updated, pending_deletes, is_error as i64,
        ],
    ).map_err(|e| format!("Save message failed: {}", e))?;
    let msg_id = conn.last_insert_rowid();

    conn.execute(
        "UPDATE describe_sessions SET updated_at = datetime('now') WHERE id = ?",
        [session_id],
    ).ok();

    // Auto-title the session from the first user message.
    if role == "user" {
        let has_title: bool = conn.query_row(
            "SELECT title IS NOT NULL FROM describe_sessions WHERE id = ?",
            [session_id], |r| r.get(0),
        ).unwrap_or(true);
        if !has_title {
            let title: String = display.chars().take(48).collect();
            conn.execute(
                "UPDATE describe_sessions SET title = ? WHERE id = ?",
                rusqlite::params![title, session_id],
            ).ok();
        }
    }

    Ok(json!({ "id": msg_id }))
}

#[tauri::command]
pub fn resolve_describe_delete(message_id: i64, resolution: String, nodes_deleted: i64) -> Result<(), String> {
    let conn = open_db()?;
    conn.execute(
        "UPDATE describe_messages SET delete_resolution = ?, nodes_deleted = ? WHERE id = ?",
        rusqlite::params![resolution, nodes_deleted, message_id],
    ).map_err(|e| format!("Resolve delete failed: {}", e))?;
    Ok(())
}

#[tauri::command]
pub fn rename_describe_session(session_id: i64, title: String) -> Result<(), String> {
    let conn = open_db()?;
    let title = title.trim();
    if title.is_empty() { return Ok(()); }
    conn.execute(
        "UPDATE describe_sessions SET title = ? WHERE id = ?",
        rusqlite::params![title, session_id],
    ).map_err(|e| format!("Rename session failed: {}", e))?;
    Ok(())
}

#[tauri::command]
pub fn delete_describe_session(session_id: i64) -> Result<(), String> {
    let conn = open_db()?;
    conn.execute("DELETE FROM describe_messages WHERE session_id = ?", [session_id])
        .map_err(|e| format!("Delete session messages failed: {}", e))?;
    conn.execute("DELETE FROM describe_sessions WHERE id = ?", [session_id])
        .map_err(|e| format!("Delete session failed: {}", e))?;
    Ok(())
}


// ─── Agentic Describe ────────────────────────────────────────────────────────
//
// These two commands put the backend's eight Describe specialists (query,
// authoring, update, deletion, validation, solution, greenfield, brownfield)
// behind the Describe screen. Until now that whole agent layer was reachable
// only from the command line and a Flask blueprint, while the UI ran its own
// client-side LLM turn -- so the agents shipped but nobody could use them.
//
// Deliberately spawns run_describe.py rather than calling the Flask
// /api/agent/describe route, for exactly the reason fetch_svg_export documents:
// security.py installs a fail-closed guard requiring a Bearer token on every
// /api/* request and this app holds no Studio session, so that route answers
// 401. Spawning keeps the desktop Flask-free.

/// Marker prefix that run_describe.py --json puts on its single result line.
/// The agents stream NDJSON progress on the same stdout, so the result cannot
/// be found by parsing the whole stream.
const DESCRIBE_RESULT_SENTINEL: &str = "@@DESCRIBE_RESULT@@ ";

/// Run one describe turn (or resolution) and return its parsed JSON result.
fn run_describe_script(args: Vec<String>) -> Result<Value, String> {
    let python = find_python()?;
    let (_, hub) = find_cli_and_hub()?;
    let script = find_studio_script("run_describe.py").ok_or_else(|| {
        "run_describe.py not found — make sure the backend folder is next to the frontend"
            .to_string()
    })?;
    let studio_dir = script
        .parent()
        .ok_or_else(|| "run_describe.py has no parent directory".to_string())?;

    let mut cmd = std::process::Command::new(&python);
    cmd.current_dir(studio_dir)
        .arg(&script)
        .arg(&hub);
    for a in &args {
        cmd.arg(a);
    }
    cmd.arg("--json").env("ENGINEERING_HUB", &hub);

    let out = cmd
        .output()
        .map_err(|e| format!("Failed to run the describe agent: {}", e))?;

    let stdout = String::from_utf8_lossy(&out.stdout);
    for line in stdout.lines() {
        if let Some(rest) = line.strip_prefix(DESCRIBE_RESULT_SENTINEL) {
            return serde_json::from_str::<Value>(rest.trim())
                .map_err(|e| format!("Describe agent returned invalid JSON: {}", e));
        }
    }

    // No result line: surface the agent's own error text rather than a bare
    // exit code, which is all the user would otherwise see.
    let stderr = String::from_utf8_lossy(&out.stderr);
    let detail = if !stderr.trim().is_empty() {
        stderr.trim().to_string()
    } else if !stdout.trim().is_empty() {
        stdout.trim().to_string()
    } else {
        format!("exit code {:?}", out.status.code())
    };
    let tail: String = detail.lines().rev().take(6).collect::<Vec<_>>()
        .into_iter().rev().collect::<Vec<_>>().join("\n");
    Err(format!("Describe agent produced no result — {}", tail))
}

/// One engineer message -> one specialist agent turn.
///
/// Returns `{status:"ok", agent, reply, title, solution_design, ops}` or
/// `{status:"pending_delete", pending_delete:{...}}` when the Deletion agent
/// pauses on its confirmation interrupt.
#[tauri::command]
pub async fn describe_agent_turn(
    project_id: String,
    message: String,
    session_id: Option<String>,
) -> Result<Value, String> {
    let message = message.trim().to_string();
    if message.is_empty() {
        return Err("Message is required".to_string());
    }
    let session = session_id.unwrap_or_else(|| "desktop".to_string());
    run_describe_script(vec![project_id, message, "--session".into(), session])
}

/// Confirm or cancel a deletion the agent paused on.
#[tauri::command]
pub async fn describe_agent_resolve(
    project_id: String,
    session_id: Option<String>,
    confirmed: bool,
) -> Result<Value, String> {
    let session = session_id.unwrap_or_else(|| "desktop".to_string());
    let choice = if confirmed { "confirm" } else { "cancel" };
    run_describe_script(vec![
        project_id,
        "--session".into(),
        session,
        "--resolve".into(),
        choice.into(),
    ])
}

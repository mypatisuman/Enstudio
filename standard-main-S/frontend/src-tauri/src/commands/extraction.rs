use serde_json::{json, Value};

use std::sync::Arc;

use tauri::Emitter;

use crate::database::{find_python, find_cli_and_hub, open_db};

use crate::config::load_config_key;

use crate::state::{ProcessState, CredentialsState};

#[tauri::command]
pub async fn run_extraction(
    app:        tauri::AppHandle,
    process:    tauri::State<'_, ProcessState>,
    creds:      tauri::State<'_, CredentialsState>,
    project_id: String,
    source_id:  i64,
    llm_only:   Option<bool>,
) -> Result<Value, String> {
    // Reject only if THIS project already has an extraction running —
    // other projects may run concurrently.
    if process.child.lock().unwrap().contains_key(&project_id) {
        return Err("Extraction already running for this project — cancel it first".to_string());
    }

    // Look up the filename from the sources table
    let conn = open_db()?;
    let filename: String = conn
        .query_row(
            "SELECT filename FROM sources WHERE id = ? AND pid = ?",
            rusqlite::params![source_id, project_id],
            |row| row.get(0),
        )
        .map_err(|e| format!("Source {} not found: {}", source_id, e))?;

    let python        = find_python()?;
    // find_cli_and_hub() resolves the configured engine: extract_cli.py
    // (classic CV + LLM verification) or run_agentic.py (LangGraph
    // multi-agent). Both speak the same NDJSON contract and take the same
    // positional args plus --source-id / --llm-only, so nothing below changes.
    let engine        = crate::database::extraction_engine();
    let (cli, hub)    = find_cli_and_hub()?;
    let api_key          = creds.api_key.lock().unwrap().clone();
    let gemini_key       = creds.gemini_key.lock().unwrap().clone();
    let openai_key       = creds.openai_key.lock().unwrap().clone();

    // Build the full PDF path so the CLI can read it. Goes through
    // project_dir so an unsafe project_id cannot point the spawned Python
    // process at a file outside the hub.
    let pdf_path = crate::database::project_dir(&project_id)
        .ok_or("Invalid project id, or no studio.db found")?
        .join("source_docs")
        .join(&filename);

    // Run from the backend/ directory so relative imports work
    let studio_dir = cli.parent().expect("cli path has no parent");

    let provider = load_config_key("llm_provider")
        .unwrap_or_else(|| "anthropic".to_string());
    let model_arg = if provider == "gemini" {
        load_config_key("gemini_model_smart")
            .unwrap_or_else(|| "gemini-2.0-flash".to_string())
    } else if provider == "openai" {
        load_config_key("openai_model_smart")
            .unwrap_or_else(|| "gpt-5.5".to_string())
    } else if let Some(preset_id) = provider.strip_prefix("custom:") {
        load_config_key(&format!("custom_{}_model", preset_id)).unwrap_or_default()
    } else {
        load_config_key("anthropic_model_smart")
            .unwrap_or_else(|| "claude-sonnet-4-6".to_string())
    };

    use std::process::Stdio;
    let mut cmd = std::process::Command::new(&python);
    cmd.current_dir(studio_dir)
        .arg(&cli)
        .arg(&hub)
        .arg(&project_id)
        .arg(&pdf_path)
        // Phase 5: pass the document identity through instead of resolving it
        // to a filename and dropping it. Without this the CLI cannot tell
        // which uploaded PDF it is extracting, so its nodes cannot be
        // attributed to a document and a second PDF overwrote the first.
        .arg("--source-id")
        .arg(source_id.to_string());
    if llm_only.unwrap_or(false) {
        // Re-extraction: YOLO/OCR/UNet output is deterministic and already
        // cached from the first run — only the two LLM stages need to run
        // again, sequentially (connections consumes verify's node list).
        cmd.arg("--llm-only");
    }
    cmd.env("ENGINEERING_HUB", &hub)
        .env("ANTHROPIC_API_KEY", &api_key)
        .env("GEMINI_API_KEY", &gemini_key)
        .env("OPENAI_API_KEY", &openai_key)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = cmd.spawn()
        .map_err(|e| format!("Failed to spawn Python: {}", e))?;

    // Tell the UI which engine produced the run it is about to stream, so a
    // result can be attributed to an engine after the fact.
    let _ = app.emit("extraction-progress", &json!({
        "stage":      "engine",
        "status":     "selected",
        "engine":     &engine,
        "script":     cli.file_name().map(|s| s.to_string_lossy().to_string()),
        "project_id": &project_id,
    }));

    let pid          = child.id();
    let stdout_pipe  = child.stdout.take().unwrap();
    let stderr_pipe  = child.stderr.take().unwrap();

    // Store for cancellation; Arc clone lets background thread clean up too
    let child_arc = Arc::clone(&process.child);
    child_arc.lock().unwrap().insert(project_id.clone(), child);

    // Background thread: stream NDJSON lines as Tauri events
    let app2            = app.clone();
    let child_arc2      = Arc::clone(&child_arc);
    let pid_for_usage   = project_id.clone();
    let file_for_usage  = filename.clone();
    let model_for_usage = model_arg.clone();
    let prov_for_usage  = provider.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader, Read};

        // Collect stderr concurrently
        let stderr_thread = std::thread::spawn(move || {
            let mut s = String::new();
            BufReader::new(stderr_pipe).read_to_string(&mut s).ok();
            s
        });

        // True only when extraction produced at least one node and emitted "done"
        let mut extraction_succeeded = false;

        // Emit each NDJSON line as an event; intercept "done" to write usage
        for line in BufReader::new(stdout_pipe).lines() {
            let Ok(line) = line else { break };
            let line = line.trim().to_string();
            if line.is_empty() { continue; }
            let mut payload: Value = serde_json::from_str(&line)
                .unwrap_or_else(|_| json!({ "stage": "log", "message": line }));
            if let Some(obj) = payload.as_object_mut() {
                obj.insert("project_id".to_string(), json!(pid_for_usage));
            }
            let _ = app2.emit("extraction-progress", &payload);

            // Persist token/cost to cache_manifest so UsageScreen shows live data
            if payload["stage"].as_str() == Some("done") {
                // Phase 1: "nodes > 0" used to be the whole success test, so a
                // run whose LLM-B stage failed and produced zero edges was
                // marked COMPLETE. The CLI now reports an explicit status;
                // only SUCCESS may set COMPLETE. PARTIAL and FAILED both
                // leave the source flagged uploaded-but-not-complete so the
                // Ingest screen keeps offering re-extraction.
                let total_nodes = payload["total_nodes"].as_i64().unwrap_or(0);
                let status = payload["status"].as_str()
                    // Older CLI builds emitted no status field; fall back to
                    // the previous rule so a mixed install still works.
                    .unwrap_or(if total_nodes > 0 { "SUCCESS" } else { "FAILED" });
                extraction_succeeded = status == "SUCCESS" && total_nodes > 0;
                if !extraction_succeeded {
                    eprintln!(
                        "[run_extraction] {} finished status={} reason={} nodes={}",
                        pid_for_usage, status,
                        payload["reason"].as_str().unwrap_or("-"),
                        total_nodes
                    );
                }
                let tokens_in  = payload["tokens_in"].as_i64().unwrap_or(0);
                let tokens_out = payload["tokens_out"].as_i64().unwrap_or(0);
                let cost_usd   = payload["cost_usd"].as_f64().unwrap_or(0.0);
                let total_tok  = tokens_in + tokens_out;
                if total_tok > 0 || cost_usd > 0.0 {
                    if let Ok(conn) = crate::database::open_db() {
                        let ts: String = conn.query_row("SELECT strftime('%Y-%m-%dT%H:%M:%SZ', 'now')", [], |r| r.get(0))
                            .unwrap_or_default();
                        let scan_entry = json!({
                            "filename":  file_for_usage,
                            "model":     model_for_usage,
                            "provider":  prov_for_usage,
                            "tokens_in": tokens_in,
                            "tokens_out":tokens_out,
                            "cost_usd":  cost_usd,
                            "timestamp": ts,
                            "pass":      1
                        });
                        // Read existing scans array, append, write back
                        let existing: String = conn.query_row(
                            "SELECT COALESCE(scan_json, '[]') FROM cache_manifest WHERE pid = ?",
                            [&pid_for_usage], |r| r.get(0)
                        ).unwrap_or_else(|_| "[]".to_string());
                        let mut scans: Vec<Value> = serde_json::from_str(&existing).unwrap_or_default();
                        scans.push(scan_entry);
                        let scans_str = serde_json::to_string(&scans).unwrap_or_else(|_| "[]".to_string());
                        let _ = conn.execute(
                            "INSERT INTO cache_manifest (pid, scan_json, total_tokens, total_cost, last_scan)
                             VALUES (?, ?, ?, ?, datetime('now'))
                             ON CONFLICT(pid) DO UPDATE SET
                               scan_json    = excluded.scan_json,
                               total_tokens = total_tokens + excluded.total_tokens,
                               total_cost   = total_cost   + excluded.total_cost,
                               last_scan    = datetime('now')",
                            rusqlite::params![pid_for_usage, scans_str, total_tok, cost_usd]
                        );
                    }
                }
            }
        }

        let stderr_content = stderr_thread.join().unwrap_or_default();

        // Reap the child to avoid zombies; clear the stored handle.
        // Set cached=1 (COMPLETE) only when extraction actually produced nodes.
        // Reset to cached=0 (UPLOADED) on failure so the status doesn't
        // falsely show COMPLETE from a previous successful run.
        {
            let mut g = child_arc2.lock().unwrap();
            if let Some(mut c) = g.remove(&pid_for_usage) {
                let _ = c.wait();
                if let Ok(conn) = crate::database::open_db() {
                    let cached_val: i64 = if extraction_succeeded { 1 } else { 0 };
                    let _ = conn.execute(
                        "UPDATE sources SET cached = ? WHERE id = ?",
                        rusqlite::params![cached_val, source_id]
                    );
                    // Record the real completion time so "last extracted" reflects
                    // an actual extraction run, not just when the file was uploaded.
                    if extraction_succeeded {
                        let _ = conn.execute(
                            "UPDATE projects SET last_extraction = datetime('now'), last_activity = datetime('now') WHERE id = ?",
                            rusqlite::params![pid_for_usage]
                        );
                    }
                }
            }
        }

        // Emit terminal event
        let stderr_trimmed = stderr_content.trim();
        let _ = app2.emit("extraction-progress", json!({
            "project_id": pid_for_usage,
            "stage":  "finished",
            "stderr": if stderr_trimmed.is_empty() { Value::Null }
                      else { Value::String(stderr_trimmed.to_string()) }
        }));
    });

    Ok(json!({ "started": true, "pid": pid }))
}

#[tauri::command]
pub fn cancel_extraction(process: tauri::State<'_, ProcessState>, project_id: String) -> Value {
    let mut g = process.child.lock().unwrap();
    if let Some(mut c) = g.remove(&project_id) {
        c.kill().ok();
        c.wait().ok();
        json!({ "cancelled": true })
    } else {
        json!({ "cancelled": false, "reason": "no process running for this project" })
    }
}

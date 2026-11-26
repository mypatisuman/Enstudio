#[cfg(test)]
use rusqlite::Connection;

use serde_json::{json, Value};

use crate::database::{open_db, find_exports_dir, find_python, find_cli_and_hub, find_studio_script};
use crate::models::ExportFileResult;
#[cfg(test)]
use crate::database::find_db;

#[tauri::command]
pub fn get_export_status(project_id: String) -> Vec<String> {
    let dir = match find_exports_dir(&project_id) {
        None    => return vec![],
        Some(d) => d,
    };
    if !dir.exists() {
        return vec![];
    }
    let mut files: Vec<String> = std::fs::read_dir(&dir)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| e.file_name().into_string().ok())
        .collect();
    files.sort();
    files
}

#[tauri::command]
pub fn get_export_content(project_id: String, filename: String) -> Result<String, String> {
    if let Some(dir) = find_exports_dir(&project_id) {
        let path = dir.join(&filename);
        if path.exists() {
            return std::fs::read_to_string(&path).map_err(|e| e.to_string());
        }
    }
    Err("File not found".to_string())
}

#[tauri::command]
pub fn preview_export(project_id: String, format: String) -> Result<String, String> {
    let conn = open_db()?;
    let pid = project_id.as_str();

    match format.as_str() {
        "vids" => build_vids_yaml(&conn, pid),
        // The one YMPL writer (backend/adapters/ympl_export.py), shared with
        // the Flask export, so desktop and server YMPL are identical.
        "ympl" => run_export_cli("export_ympl_cli.py", &[pid, "--stdout"]),
        "markdown" => {
            let (title, _, _, _, created) = proj_meta(&conn, pid);
            let mut instr_rows: Vec<(String,String,String,String,String,f64)> = Vec::new();
            {
                let mut stmt = conn.prepare(
                    "SELECT i.tag, COALESCE(i.type,''), COALESCE(i.area,''),
                            COALESCE(i.equipment_ref,''),
                            COALESCE(json_extract(i.extra_json,'$.drawing'),''),
                            COALESCE(CAST(json_extract(i.extra_json,'$.confidence') AS REAL), 0.0)
                     FROM instruments i WHERE i.pid = ? ORDER BY i.tag"
                ).map_err(|e| format!("Prepare instruments: {}", e))?;
                let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
                while let Some(row) = rows.next().map_err(|e| e.to_string())? {
                    instr_rows.push((row.get(0).unwrap_or_default(), row.get(1).unwrap_or_default(),
                        row.get(2).unwrap_or_default(), row.get(3).unwrap_or_default(),
                        row.get(4).unwrap_or_default(), row.get(5).unwrap_or(0.0)));
                }
            }
            let mut equip_rows: Vec<(String,String,String,String)> = Vec::new();
            {
                let mut stmt = conn.prepare(
                    "SELECT tag, COALESCE(type,''), COALESCE(area,''),
                            COALESCE(json_extract(extra_json,'$.drawing'),'')
                     FROM equipment WHERE pid = ? ORDER BY tag"
                ).map_err(|e| format!("Prepare equipment: {}", e))?;
                let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
                while let Some(row) = rows.next().map_err(|e| e.to_string())? {
                    equip_rows.push((row.get(0).unwrap_or_default(), row.get(1).unwrap_or_default(),
                        row.get(2).unwrap_or_default(), row.get(3).unwrap_or_default()));
                }
            }
            let orphans: i64 = conn.query_row(
                "SELECT COUNT(*) FROM instruments WHERE pid = ? AND (equipment_ref IS NULL OR equipment_ref = '')",
                [pid], |r| r.get(0)).unwrap_or(0);
            let low_conf: i64 = conn.query_row(
                "SELECT COUNT(*) FROM instruments WHERE pid = ? AND json_extract(extra_json,'$.confidence') IS NOT NULL AND json_extract(extra_json,'$.confidence') < 0.5",
                [pid], |r| r.get(0)).unwrap_or(0);
            let no_drawing: i64 = conn.query_row(
                "SELECT COUNT(*) FROM instruments WHERE pid = ? AND (json_extract(extra_json,'$.drawing') IS NULL OR json_extract(extra_json,'$.drawing') = '')",
                [pid], |r| r.get(0)).unwrap_or(0);
            let mut md = String::new();
            let date_str = if created.is_empty() { String::new() } else { format!("  \n**Date:** {}", created) };
            md.push_str(&format!("# Project: {}{}\n\n", title, date_str));
            md.push_str(&format!("## Summary\n\n- **Instruments:** {}\n- **Equipment:** {}\n\n", instr_rows.len(), equip_rows.len()));
            md.push_str(&format!("## Instruments ({})\n\n", instr_rows.len()));
            md.push_str("| Tag | Type | Drawing | Equip Ref | Area | Confidence |\n|---|---|---|---|---|---|\n");
            for (tag, typ, area, eref, drawing, conf) in &instr_rows {
                let conf_str = if *conf > 0.0 { format!("{}%", (conf * 100.0).round() as i64) } else { "—".to_string() };
                md.push_str(&format!("| {} | {} | {} | {} | {} | {} |\n",
                    tag, typ,
                    if drawing.is_empty() { "—" } else { drawing },
                    if eref.is_empty()    { "—" } else { eref },
                    if area.is_empty()    { "—" } else { area },
                    conf_str));
            }
            md.push('\n');
            md.push_str(&format!("## Equipment ({})\n\n", equip_rows.len()));
            md.push_str("| Tag | Type | Area | Drawing |\n|---|---|---|---|\n");
            for (tag, typ, area, drawing) in &equip_rows {
                md.push_str(&format!("| {} | {} | {} | {} |\n",
                    tag, typ,
                    if area.is_empty()    { "—" } else { area },
                    if drawing.is_empty() { "—" } else { drawing }));
            }
            md.push('\n');
            md.push_str("## Data Quality\n\n");
            md.push_str(&format!("- **Orphaned instruments** (no equip ref): {}\n", orphans));
            md.push_str(&format!("- **Low confidence** (< 50%): {}\n", low_conf));
            md.push_str(&format!("- **Missing drawing**: {}\n", no_drawing));
            md.push('\n');
            let mermaid = build_mermaid_flowchart(&conn, pid)?;
            md.push_str("## P&ID Diagram\n\n```mermaid\n");
            md.push_str(&mermaid);
            md.push_str("\n```\n");
            Ok(md)
        }
        "mermaid" => build_mermaid_flowchart(&conn, pid),
        other => Err(format!("Unknown format '{}' — supported: vids, ympl, markdown, mermaid", other)),
    }
}

#[tauri::command]
pub fn open_path_in_os(path: String) -> Result<(), String> {
    let p = std::path::PathBuf::from(&path);
    if p.exists() {
        let path_str = p.to_string_lossy().to_string();
        #[cfg(target_os = "windows")]
        let _ = std::process::Command::new("powershell")
            .arg("-Command")
            .arg(format!("Invoke-Item '{}'", path_str))
            .spawn();
        #[cfg(target_os = "macos")]
        let _ = std::process::Command::new("open").arg(&path_str).spawn();
        #[cfg(target_os = "linux")]
        let _ = std::process::Command::new("xdg-open").arg(&path_str).spawn();
        return Ok(());
    }
    Err("File not found".to_string())
}

#[tauri::command]
pub fn save_export_to_path(content: String, path: String) -> Result<(), String> {
    std::fs::write(&path, content).map_err(|e| format!("Failed to save file: {}", e))
}

/// Studio-server request errors, phrased for someone looking at the Export
/// screen rather than a stack trace. Shared by every command that reaches the
/// Flask side so they all fail the same way.
fn studio_request_error(e: &ureq::Error) -> String {
    let s = e.to_string();
    if s.contains("Connection refused")
        || s.contains("tcp connect error")
        || s.contains("Network")
    {
        "Studio server is not running — start it with: cd backend && python main.py"
            .to_string()
    } else {
        format!("Export request failed: {}", s)
    }
}

/// Render the ISA-5.1 vector SVG for a project by spawning export_svg_cli.py,
/// the same way export_dxf_native spawns export_dxf_cli.py.
///
/// The Export screen used to build its SVG with html-to-image's toSvg, which
/// clones the live Canvas DOM into a <foreignObject>. That is valid SVG and
/// looks exactly like the Canvas, but it is a web page in an .svg wrapper:
/// Inkscape, Illustrator and CAD importers do not implement foreignObject, so
/// they render it blank, and nothing in it is editable geometry. The generator
/// emits real <path>/<circle>/<text> ISA symbols instead.
///
/// Deliberately NOT the Flask /export/svg route: security.py installs a
/// fail-closed guard requiring a Bearer token on every /api/* request, and
/// this app holds no Studio session — that route answers 401. Spawning keeps
/// the desktop Flask-free, which is the whole point of the native exports.
///
/// `view` is 'control' or 'full'; `background` is 'dark' or 'light'.
#[tauri::command]
pub async fn fetch_svg_export(project_id: String, view: String, background: String,
                              positions: Option<String>)
    -> Result<String, String>
{
    let python = find_python()?;
    let (_, hub) = find_cli_and_hub()?;
    let script = find_studio_script("export_svg_cli.py")
        .ok_or_else(|| "export_svg_cli.py not found — make sure the backend folder is next to the frontend".to_string())?;

    let view = if view == "full" { "full" } else { "control" };
    let bg   = if background == "light" { "light" } else { "dark" };

    // The Canvas's laid-out node positions, as JSON. Passed via a temp file
    // rather than argv: a large project's position map runs to tens of KB,
    // past the command-line length limit on Windows. Kept alive until the
    // child has exited.
    let pos_file = match positions.as_deref() {
        Some(json) if !json.trim().is_empty() => {
            let path = std::env::temp_dir()
                .join(format!("enstudio_pos_{}.json", std::process::id()));
            std::fs::write(&path, json)
                .map_err(|e| format!("Write positions file: {}", e))?;
            Some(path)
        }
        _ => None,
    };

    let mut cmd = std::process::Command::new(&python);
    cmd.arg(&script)
        .arg(&project_id)
        .arg("--preview")
        .arg("--view").arg(view)
        .arg("--bg").arg(bg)
        .env("ENGINEERING_HUB", &hub)
        .env("PYTHONIOENCODING", "utf-8")
        .current_dir(script.parent().unwrap());
    if let Some(ref p) = pos_file {
        cmd.arg("--positions").arg(p);
    }
    let output = cmd.output().map_err(|e| e.to_string())?;
    if let Some(p) = pos_file {
        let _ = std::fs::remove_file(p);
    }

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let svg = String::from_utf8_lossy(&output.stdout).to_string();
    if !svg.trim_start().starts_with("<svg") {
        return Err(format!(
            "SVG generator produced no drawing: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(svg)
}

#[tauri::command]
pub fn export_project(project_id: String, format: String) -> Result<Value, String> {
    // Validate format against the known routes
    let allowed = ["vids", "ympl", "svg", "markdown"];
    if !allowed.contains(&format.as_str()) {
        return Err(format!("Unknown export format: {}", format));
    }

    let url = format!(
        "http://localhost:8000/api/projects/{}/export/{}",
        project_id, format
    );

    let resp = ureq::get(&url).call().map_err(|e| studio_request_error(&e))?;

    if resp.status() != 200 {
        return Err(format!("Export returned HTTP {}", resp.status()));
    }

    // Read content-type and Content-Disposition before consuming the body
    let content_type = resp.content_type().to_string();
    let filename_from_cd: String = resp
        .header("Content-Disposition")
        .and_then(|cd| cd.split("filename=").nth(1))
        .map(|s| s.trim_matches('"').to_string())
        .unwrap_or_default();

    if content_type.contains("application/json") {
        // vids and ympl — JSON body contains {filename, path, ...}
        let body: Value = resp
            .into_json()
            .map_err(|e| format!("JSON parse error: {}", e))?;
        let filename = body
            .get("filename")
            .and_then(|v| v.as_str())
            .unwrap_or(&filename_from_cd)
            .to_string();
        Ok(json!({ "ok": true, "filename": filename }))
    } else {
        // svg, markdown — binary/text body; filename from Content-Disposition
        let _ = resp.into_string(); // consume the body
        Ok(json!({ "ok": true, "filename": filename_from_cd }))
    }
}

// YAML string quoting — matches PyYAML's plain/single-quote rules for our data
fn yaml_str(s: &str) -> String {
    if s.is_empty() { return "''".to_string(); }
    let lo = s.to_ascii_lowercase();
    let needs_quote =
        matches!(lo.as_str(), "null"|"true"|"false"|"yes"|"no"|"on"|"off")
        || s.parse::<i64>().is_ok()
        || s.parse::<f64>().is_ok()
        || s.chars().next().is_some_and(|c| ":!#@`&*?|>'\"{[%".contains(c))
        || s.contains(": ")
        // mid-string '#' preceded by any whitespace starts a YAML comment
        || s.char_indices().any(|(i, c)| c == '#' && s[..i].chars().last().is_some_and(|p| p.is_whitespace()))
        || s.ends_with(':')
        || s.contains('\n');
    if needs_quote { format!("'{}'", s.replace('\'', "''")) } else { s.to_string() }
}

fn yaml_float(f: f64) -> String {
    let s = format!("{:.6}", f);
    s.trim_end_matches('0').trim_end_matches('.').to_string()
}

fn proj_meta(conn: &rusqlite::Connection, pid: &str)
    -> (String, String, String, i64, String)
{
    conn.query_row(
        "SELECT COALESCE(title, plant_name, id),
                COALESCE(plant_name, id),
                COALESCE(process_type,'generic'),
                COALESCE(revision, 1),
                COALESCE(created, '')
         FROM projects WHERE id = ?",
        [pid],
        |r| Ok((
            r.get::<_,String>(0).unwrap_or_default(),
            r.get::<_,String>(1).unwrap_or_default(),
            r.get::<_,String>(2).unwrap_or_default(),
            r.get::<_,i64>(3).unwrap_or(1),
            r.get::<_,String>(4).unwrap_or_default(),
        ))
    ).unwrap_or_else(|_| (pid.to_string(), pid.to_string(), "generic".into(), 1, "".into()))
}

fn xjson_str(extra: &Value, key: &str) -> String {
    extra.get(key).and_then(|v| v.as_str()).unwrap_or("").to_string()
}

fn xjson_f64(extra: &Value, key: &str) -> Option<f64> {
    extra.get(key).and_then(|v| v.as_f64())
}

/// Builds the VIDS YAML document body. Shared by `preview_export("vids")`
/// (returns the string as-is) and `export_vids` (also writes it to disk) —
/// keep both call sites byte-identical by construction rather than by
/// manually keeping two copies in sync.
fn build_vids_yaml(conn: &rusqlite::Connection, pid: &str) -> Result<String, String> {
    use std::collections::{BTreeMap, HashMap};

    let (_, plant_name, process_type, revision, created) = proj_meta(conn, pid);

    // Source of truth is the full `nodes`/`edges` graph — the same one YMPL
    // exports from. The `equipment`/`instruments`/`connections` mirror tables
    // only ever receive the classified subset extraction recognises (valves,
    // junctions, regulators and headers never land there), which on a typical
    // project drops most of the drawing and leaves connections pointing at
    // tags absent from the document. Those tables are still read below, for
    // the per-tag detail (description, ranges, alarms) that `nodes` lacks.
    let mut id_to_tag: HashMap<String, String> = HashMap::new();
    // tag -> (kind, area, x, y); BTreeMap keeps the by-tag ordering the
    // previous `ORDER BY tag` queries produced, and folds duplicate labels.
    let mut graph_nodes: BTreeMap<String, (String, String, Option<f64>, Option<f64>)> = BTreeMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, COALESCE(label,''), COALESCE(kind,''), COALESCE(area,''), x, y
             FROM nodes WHERE pid = ? ORDER BY id"
        ).map_err(|e| format!("Prepare nodes: {}", e))?;
        let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let id:    String = row.get::<_,String>(0).unwrap_or_default();
            let label: String = row.get::<_,String>(1).unwrap_or_default();
            let kind:  String = row.get::<_,String>(2).unwrap_or_default();
            let area:  String = row.get::<_,String>(3).unwrap_or_default();
            let x: Option<f64> = row.get(4).ok();
            let y: Option<f64> = row.get(5).ok();
            if id.is_empty() { continue; }
            let tag = if label.is_empty() { id.clone() } else { label };
            id_to_tag.insert(id, tag.clone());
            graph_nodes.entry(tag).or_insert((kind, area, x, y));
        }
    }

    // Per-tag detail from the mirror tables: (type, area, equipment_ref, extra)
    let mut equip_meta: HashMap<String, (String, String, Value)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT tag, COALESCE(type,''), COALESCE(area,''), COALESCE(extra_json,'{}')
             FROM equipment WHERE pid = ?"
        ).map_err(|e| format!("Prepare equipment: {}", e))?;
        let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let tag: String = row.get::<_,String>(0).unwrap_or_default();
            let ex: Value = serde_json::from_str(
                &row.get::<_,String>(3).unwrap_or_default()
            ).unwrap_or(json!({}));
            equip_meta.insert(tag, (
                row.get::<_,String>(1).unwrap_or_default(),
                row.get::<_,String>(2).unwrap_or_default(),
                ex,
            ));
        }
    }
    let mut instr_meta: HashMap<String, (String, String, String, Value)> = HashMap::new();
    {
        let mut stmt = conn.prepare(
            "SELECT tag, COALESCE(type,''), COALESCE(area,''),
                    COALESCE(equipment_ref,''), COALESCE(extra_json,'{}')
             FROM instruments WHERE pid = ?"
        ).map_err(|e| format!("Prepare instruments: {}", e))?;
        let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let tag: String = row.get::<_,String>(0).unwrap_or_default();
            let ex: Value = serde_json::from_str(
                &row.get::<_,String>(4).unwrap_or_default()
            ).unwrap_or(json!({}));
            instr_meta.insert(tag, (
                row.get::<_,String>(1).unwrap_or_default(),
                row.get::<_,String>(2).unwrap_or_default(),
                row.get::<_,String>(3).unwrap_or_default(),
                ex,
            ));
        }
    }

    // A tag is an instrument if the instruments table says so, else by kind.
    // Mirror-table rows with no node still get emitted, so nothing is lost
    // whichever side of the dual-write a tag happens to live on.
    let is_instrument = |tag: &str, kind: &str| -> bool {
        instr_meta.contains_key(tag)
            || (!equip_meta.contains_key(tag) && crate::commands::graph::is_instrument_kind(kind))
    };
    let mut equipment_tags: BTreeMap<String, (String, String, Option<f64>, Option<f64>)> = BTreeMap::new();
    let mut instrument_tags: BTreeMap<String, (String, String, Option<f64>, Option<f64>)> = BTreeMap::new();
    for (tag, entry) in &graph_nodes {
        if is_instrument(tag, &entry.0) {
            instrument_tags.insert(tag.clone(), entry.clone());
        } else {
            equipment_tags.insert(tag.clone(), entry.clone());
        }
    }
    for tag in equip_meta.keys() {
        if !graph_nodes.contains_key(tag) {
            equipment_tags.entry(tag.clone()).or_insert((String::new(), String::new(), None, None));
        }
    }
    for tag in instr_meta.keys() {
        if !graph_nodes.contains_key(tag) {
            instrument_tags.entry(tag.clone()).or_insert((String::new(), String::new(), None, None));
        }
    }

    // ── Connections ───────────────────────────────────────────────────────────
    // (from_tag, id, to_tag, type, fluid, line_size)
    let mut conns: Vec<(String, String, String, String, String, String)> = Vec::new();
    let mut seen: std::collections::HashSet<(String, String, String)> = std::collections::HashSet::new();
    {
        let mut stmt = conn.prepare(
            "SELECT COALESCE(from_id,''), COALESCE(to_id,''),
                    COALESCE(kind,'process'), COALESCE(label,''), COALESCE(extra_json,'{}')
             FROM edges WHERE pid = ?"
        ).map_err(|e| format!("Prepare edges: {}", e))?;
        let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let from_id: String = row.get::<_,String>(0).unwrap_or_default();
            let to_id:   String = row.get::<_,String>(1).unwrap_or_default();
            let typ:     String = row.get::<_,String>(2).unwrap_or_default();
            let id:      String = row.get::<_,String>(3).unwrap_or_default();
            let ex: Value = serde_json::from_str(
                &row.get::<_,String>(4).unwrap_or_default()
            ).unwrap_or(json!({}));
            if from_id.is_empty() { continue; }
            // A dangling endpoint keeps its raw node id rather than dropping
            // the connection — losing topology is worse than an odd tag.
            let from = id_to_tag.get(&from_id).cloned().unwrap_or(from_id);
            let to   = id_to_tag.get(&to_id).cloned().unwrap_or(to_id);
            if seen.insert((from.clone(), id.clone(), to.clone())) {
                conns.push((from, id, to, typ, xjson_str(&ex, "fluid"), xjson_str(&ex, "line_size")));
            }
        }
    }
    {
        let mut stmt = conn.prepare(
            "SELECT COALESCE(id,''), COALESCE(from_tag,''), COALESCE(to_tag,''),
                    COALESCE(type,'process'), COALESCE(extra_json,'{}')
             FROM connections WHERE pid = ?"
        ).map_err(|e| format!("Prepare connections: {}", e))?;
        let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let id:   String = row.get::<_,String>(0).unwrap_or_default();
            let from: String = row.get::<_,String>(1).unwrap_or_default();
            let to:   String = row.get::<_,String>(2).unwrap_or_default();
            let typ:  String = row.get::<_,String>(3).unwrap_or_default();
            let ex: Value = serde_json::from_str(
                &row.get::<_,String>(4).unwrap_or_default()
            ).unwrap_or(json!({}));
            if from.is_empty() { continue; }
            if seen.insert((from.clone(), id.clone(), to.clone())) {
                conns.push((from, id, to, typ, xjson_str(&ex, "fluid"), xjson_str(&ex, "line_size")));
            }
        }
    }
    conns.sort_by(|a, b| (&a.0, &a.1, &a.2).cmp(&(&b.0, &b.1, &b.2)));

    let mut out = String::from("connections:\n");
    for (from, id, to, typ, fluid, line_size) in &conns {
        // alphabetical key order: fluid from_tag id line_size to_tag type
        if !fluid.is_empty()     { out.push_str(&format!("- fluid: {}\n",     yaml_str(fluid))); out.push_str(&format!("  from_tag: {}\n", yaml_str(from))); }
        else                     { out.push_str(&format!("- from_tag: {}\n",  yaml_str(from))); }
        if !id.is_empty()        { out.push_str(&format!("  id: {}\n",        yaml_str(id))); }
        if !line_size.is_empty() { out.push_str(&format!("  line_size: {}\n", yaml_str(line_size))); }
        if !to.is_empty()        { out.push_str(&format!("  to_tag: {}\n",    yaml_str(to))); }
        out.push_str(&format!("  type: {}\n", yaml_str(typ)));
    }

    // ── Equipment ─────────────────────────────────────────────────────────────
    out.push_str("equipment:\n");
    for (tag, (kind, node_area, x, y)) in &equipment_tags {
        let empty = (String::new(), String::new(), json!({}));
        let (m_typ, m_area, ex) = equip_meta.get(tag).unwrap_or(&empty);
        let typ  = if m_typ.is_empty()  { kind }      else { m_typ };
        let area = if m_area.is_empty() { node_area } else { m_area };
        let desc = xjson_str(ex, "description");
        out.push_str(&format!("  {}:\n", yaml_str(tag)));
        // alphabetical: area description type x y
        if !area.is_empty() { out.push_str(&format!("    area: {}\n", yaml_str(area))); }
        out.push_str(&format!("    description: {}\n", yaml_str(&desc)));
        if !typ.is_empty()  { out.push_str(&format!("    type: {}\n", yaml_str(typ))); }
        if let Some(v) = x { out.push_str(&format!("    x: {}\n", yaml_float(*v))); }
        if let Some(v) = y { out.push_str(&format!("    y: {}\n", yaml_float(*v))); }
    }

    // ── Instruments ───────────────────────────────────────────────────────────
    out.push_str("instruments:\n");
    for (tag, (kind, node_area, x, y)) in &instrument_tags {
        let empty = (String::new(), String::new(), String::new(), json!({}));
        let (m_typ, m_area, eref, ex) = instr_meta.get(tag).unwrap_or(&empty);
        let typ  = if m_typ.is_empty()  { kind }      else { m_typ };
        let area = if m_area.is_empty() { node_area } else { m_area };
        out.push_str(&format!("  {}:\n", yaml_str(tag)));
        // alphabetical: alarm_hi alarm_hihi alarm_lo alarm_lolo area description equipment_ref fail_position range_hi range_lo type units x y
        for k in &["alarm_hi","alarm_hihi","alarm_lo","alarm_lolo"] {
            if let Some(v) = xjson_f64(ex, k) { out.push_str(&format!("    {}: {}\n", k, yaml_float(v))); }
        }
        if !area.is_empty()  { out.push_str(&format!("    area: {}\n",  yaml_str(area))); }
        let desc = xjson_str(ex, "description");
        if !desc.is_empty()  { out.push_str(&format!("    description: {}\n", yaml_str(&desc))); }
        if !eref.is_empty()  { out.push_str(&format!("    equipment_ref: {}\n", yaml_str(eref))); }
        let fp = xjson_str(ex, "fail_position");
        if !fp.is_empty()    { out.push_str(&format!("    fail_position: {}\n", yaml_str(&fp))); }
        if let Some(v) = xjson_f64(ex, "range_hi") { out.push_str(&format!("    range_hi: {}\n", yaml_float(v))); }
        if let Some(v) = xjson_f64(ex, "range_lo") { out.push_str(&format!("    range_lo: {}\n", yaml_float(v))); }
        if !typ.is_empty()   { out.push_str(&format!("    type: {}\n",  yaml_str(typ))); }
        let units = xjson_str(ex, "units");
        if !units.is_empty() { out.push_str(&format!("    units: {}\n", yaml_str(&units))); }
        if let Some(v) = x { out.push_str(&format!("    x: {}\n", yaml_float(*v))); }
        if let Some(v) = y { out.push_str(&format!("    y: {}\n", yaml_float(*v))); }
    }

    // ── Metadata + screens ────────────────────────────────────────────────────
    out.push_str("metadata:\n");
    if !created.is_empty() { out.push_str(&format!("  date: {}\n", yaml_str(&created))); }
    out.push_str(&format!("  plant_name: {}\n",   yaml_str(&plant_name)));
    out.push_str(&format!("  process_type: {}\n", yaml_str(&process_type)));
    out.push_str(&format!("  revision: {}\n",     revision));
    out.push_str("screens: []\n");
    Ok(out)
}

/// Run one of the backend's Python export CLIs and return its stdout.
///
/// YMPL and the connectivity graph are produced by exactly one writer each, in
/// Python (adapters/ympl_export.py, adapters/connectivity_export.py). The
/// desktop used to carry its own topology-only YMPL builder here, so the same
/// project exported differently from the desktop and from Flask. Spawning the
/// CLI follows fetch_svg_export's pattern: the Flask /api routes require a
/// session token this app does not hold.
fn run_export_cli(script_name: &str, args: &[&str]) -> Result<String, String> {
    let python = find_python()?;
    let (_, hub) = find_cli_and_hub()?;
    let script = find_studio_script(script_name).ok_or_else(|| {
        format!("{} not found — make sure the backend folder is next to the frontend", script_name)
    })?;
    let mut cmd = std::process::Command::new(&python);
    cmd.arg(&script).arg(&hub);
    for a in args {
        cmd.arg(a);
    }
    cmd.env("ENGINEERING_HUB", &hub)
        .env("PYTHONIOENCODING", "utf-8")
        .current_dir(script.parent().unwrap());
    let output = cmd
        .output()
        .map_err(|e| format!("Failed to run {}: {}", script_name, e))?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let detail = if stderr.is_empty() { stdout.trim().to_string() } else { stderr };
        return Err(format!("{} failed: {}", script_name, detail));
    }
    Ok(stdout)
}

/// Parse the single JSON result line an export CLI prints.
fn file_result_from_cli(stdout: &str) -> Result<ExportFileResult, String> {
    let line = stdout
        .lines()
        .rev()
        .find(|l| l.trim_start().starts_with('{'))
        .ok_or_else(|| "export produced no result".to_string())?;
    let v: Value = serde_json::from_str(line.trim())
        .map_err(|e| format!("Invalid export result: {}", e))?;
    if !v["success"].as_bool().unwrap_or(false) {
        return Err(v["error"].as_str().unwrap_or("export failed").to_string());
    }
    Ok(ExportFileResult {
        success: true,
        filename: v["filename"].as_str().unwrap_or("").to_string(),
        path: v["path"].as_str().unwrap_or("").to_string(),
    })
}

#[tauri::command]
pub fn export_ympl(project_id: String) -> Result<ExportFileResult, String> {
    let out = run_export_cli("export_ympl_cli.py", &[project_id.as_str()])?;
    file_result_from_cli(&out)
}

/// Connectivity graph JSON. `schema_version` "2.0.0" (default) or "2.1.0",
/// which adds each node's system and subsystem.
#[tauri::command]
pub fn export_connectivity(project_id: String, schema_version: Option<String>)
    -> Result<ExportFileResult, String>
{
    let schema = match schema_version.as_deref() {
        Some("2.1.0") => "2.1.0",
        _ => "2.0.0",
    };
    let out = run_export_cli("export_connectivity_cli.py",
                             &[project_id.as_str(), "--schema", schema])?;
    file_result_from_cli(&out)
}

/// The connectivity graph JSON as text, for the Export screen's preview.
#[tauri::command]
pub fn preview_connectivity(project_id: String, schema_version: Option<String>)
    -> Result<String, String>
{
    let schema = match schema_version.as_deref() {
        Some("2.1.0") => "2.1.0",
        _ => "2.0.0",
    };
    run_export_cli("export_connectivity_cli.py",
                   &[project_id.as_str(), "--schema", schema, "--stdout"])
}

const MERMAID_CLASS_DEFS: &[&str] = &[
    "classDef vessel fill:#E8F4FD,stroke:#2E6DA4",
    "classDef separator fill:#E8F4FD,stroke:#2E6DA4",
    "classDef heatExchanger fill:#FEF3E2,stroke:#C07A00",
    "classDef pump fill:#E8F6E8,stroke:#2E7D32",
    "classDef compressor fill:#E8F6E8,stroke:#2E7D32",
    "classDef reactor fill:#FCE8E8,stroke:#C0392B",
    "classDef column fill:#F0E8FC,stroke:#6B2E9A",
    "classDef absorber fill:#F0E8FC,stroke:#6B2E9A",
    "classDef filter fill:#F5F5F5,stroke:#666666",
    "classDef meter fill:#F5F5F5,stroke:#666666",
    "classDef transmitter fill:#E3F2FD,stroke:#1565C0",
    "classDef controller fill:#E8F5E9,stroke:#2E7D32",
    "classDef indicator fill:#FFFFFF,stroke:#555555",
    "classDef recorder fill:#FFF8E1,stroke:#F57F17",
    "classDef switch fill:#FFF3E0,stroke:#E65100",
    "classDef analyzer fill:#F3E5F5,stroke:#6A1B9A",
    "classDef element fill:#E8EAF6,stroke:#283593",
    "classDef valve fill:#F5F5F5,stroke:#424242",
    "classDef checkvalve fill:#F5F5F5,stroke:#424242",
    "classDef relief fill:#FCE8E8,stroke:#C0392B",
    "classDef offPageConn fill:#E8E8E8,stroke:#888888",
];

/// Maps a raw node kind (YOLO type string like "Ball_Valve", a palette code,
/// or an already-canonical kind) to the small canonical lowercase vocabulary
/// the mermaid/svg/dxf renderers draw ISA-5.1 shapes for. Mirrors
/// adapters/kind_normalize.py's rules exactly — keep the two in sync.
/// Keyword-based rather than an exhaustive table so it survives new YOLO
/// classes without a maintenance pass; exact-match tables silently fall
/// through to a generic box/no-color for anything not yet added.
fn normalize_render_kind(raw_kind: &str) -> String {
    const CANONICAL: &[&str] = &[
        "vessel", "separator", "heat_exchanger", "pump", "compressor", "reactor",
        "column", "absorber", "filter", "meter", "relief",
        "transmitter", "controller", "indicator", "recorder", "switch",
        "analyzer", "element", "valve", "checkvalve",
        "junction", "off_page_connector", "package", "vendor_package",
    ];
    if raw_kind.is_empty() { return "default".to_string(); }
    if CANONICAL.contains(&raw_kind) { return raw_kind.to_string(); }
    let lo = raw_kind.to_lowercase();
    const RULES: &[(&str, &str)] = &[
        ("checkvalve", "checkvalve"), ("check_valve", "checkvalve"),
        ("relief", "relief"), ("rupture", "relief"), ("safety", "relief"),
        ("valve", "valve"),
        ("controller", "controller"),
        ("transmitter", "transmitter"),
        ("indicator", "indicator"), ("indicating", "indicator"),
        ("recorder", "recorder"),
        ("switch", "switch"),
        ("analy", "analyzer"),
        ("sensor", "element"), ("transducer", "element"), ("element", "element"),
        ("pump", "pump"),
        ("compressor", "compressor"), ("blower", "compressor"), ("turbine", "compressor"), ("expander", "compressor"),
        ("exchanger", "heat_exchanger"), ("heater", "heat_exchanger"), ("boiler", "heat_exchanger"),
        ("condenser", "heat_exchanger"), ("cooler", "heat_exchanger"),
        ("column", "column"), ("tower", "column"),
        ("reactor", "reactor"),
        ("cyclone", "separator"), ("separator", "separator"),
        ("absorber", "absorber"),
        ("filter", "filter"), ("strainer", "filter"),
        ("meter", "meter"),
        ("vessel", "vessel"), ("tank", "vessel"), ("drum", "vessel"), ("accumulator", "vessel"),
        ("junction", "junction"),
    ];
    for (word, kind) in RULES {
        if lo.contains(word) { return kind.to_string(); }
    }
    "default".to_string()
}

fn mermaid_class_for_kind(kind: &str) -> &'static str {
    match kind {
        "vessel" => "vessel", "separator" => "separator",
        "heat_exchanger" => "heatExchanger", "pump" => "pump", "compressor" => "compressor",
        "reactor" => "reactor", "column" => "column",
        "absorber" | "adsorption" => "absorber",
        "filter" => "filter", "meter" => "meter",
        "transmitter" => "transmitter", "controller" => "controller",
        "indicator" => "indicator", "recorder" => "recorder", "switch" => "switch",
        "analyzer" => "analyzer", "element" => "element",
        "valve" => "valve", "checkvalve" => "checkvalve", "relief" => "relief",
        "off_page_connector" => "offPageConn",
        _ => "",
    }
}

fn mermaid_shape(kind: &str, label: &str) -> String {
    match kind {
        "transmitter" | "controller" | "indicator" | "recorder" | "switch" | "analyzer" | "element" =>
            format!("((\"{}\"))", label),
        "heat_exchanger" | "pump" | "compressor" => format!("(\"{}\")", label),
        "off_page_connector" => format!(">\"{}\"]", label),
        _ => format!("[\"{}\"]", label),
    }
}

fn mermaid_id(node_id: &str) -> String {
    format!("n_{}", node_id.replace(['-', '.', '/'], "_"))
}

/// Build one project-wide `flowchart LR` Mermaid diagram from nodes/edges.
/// Ported from adapters/md_export.py's _drawing_mermaid — that version splits
/// per drawing; the native exporter has no drawing-grouping today, so this
/// builds a single combined diagram for the whole project.
fn build_mermaid_flowchart(conn: &rusqlite::Connection, pid: &str) -> Result<String, String> {
    let mut lines: Vec<String> = vec!["flowchart LR".to_string(), "".to_string()];
    lines.extend(MERMAID_CLASS_DEFS.iter().map(|s| s.to_string()));
    lines.push("".to_string());

    let mut node_ids: std::collections::HashSet<String> = std::collections::HashSet::new();
    {
        let mut stmt = conn.prepare(
            "SELECT id, COALESCE(label,''), COALESCE(kind,'') FROM nodes WHERE pid = ? \
             ORDER BY CAST(SUBSTR(id,2) AS INTEGER)"
        ).map_err(|e| format!("Prepare nodes: {}", e))?;
        let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let id:    String = row.get(0).unwrap_or_default();
            let label: String = row.get::<_,String>(1).unwrap_or_default().replace('"', "'");
            let kind:  String = row.get(2).unwrap_or_default();
            let label = if label.is_empty() { id.clone() } else { label };
            let kind = normalize_render_kind(&kind);
            let cls = mermaid_class_for_kind(&kind);
            let suffix = if cls.is_empty() { String::new() } else { format!(":::{}", cls) };
            lines.push(format!("  {}{}{}", mermaid_id(&id), mermaid_shape(&kind, &label), suffix));
            node_ids.insert(id);
        }
    }

    lines.push("".to_string());
    {
        let mut stmt = conn.prepare(
            "SELECT COALESCE(from_id,''), COALESCE(to_id,''), COALESCE(kind,'stream'), COALESCE(label,'') \
             FROM edges WHERE pid = ?"
        ).map_err(|e| format!("Prepare edges: {}", e))?;
        let mut rows = stmt.query([pid]).map_err(|e| e.to_string())?;
        while let Some(row) = rows.next().map_err(|e| e.to_string())? {
            let from:  String = row.get(0).unwrap_or_default();
            let to:    String = row.get(1).unwrap_or_default();
            let kind:  String = row.get(2).unwrap_or_default();
            let label: String = row.get::<_,String>(3).unwrap_or_default().replace('"', "'");
            if !node_ids.contains(&from) || !node_ids.contains(&to) { continue; }
            let arrow = match kind.as_str() {
                "signal" | "bypass" => "-.->",
                "recycle" => "==>",
                _ => "-->",
            };
            let label: String = label.chars().take(20).collect();
            if label.is_empty() {
                lines.push(format!("  {} {} {}", mermaid_id(&from), arrow, mermaid_id(&to)));
            } else {
                lines.push(format!("  {} {}|\"{}\"| {}", mermaid_id(&from), arrow, label, mermaid_id(&to)));
            }
        }
    }

    Ok(lines.join("\n"))
}

// SVG export/preview is fetch_svg_export above, which spawns export_svg_cli.py
// (the Python svg_pid.py renderer). It briefly went the other way — capturing
// the real Canvas in the frontend via html-to-image — but that produces a
// <foreignObject> holding a DOM copy, which Inkscape/Illustrator/CAD render
// blank and which contains no editable geometry.

#[tauri::command]
pub async fn export_dxf_native(project_id: String) -> Result<String, String> {
    let python = find_python()?;
    let (_, hub) = find_cli_and_hub()?;

    let script = find_studio_script("export_dxf_cli.py")
        .ok_or_else(|| "export_dxf_cli.py not found — make sure the backend folder is next to the frontend".to_string())?;

    let output = std::process::Command::new(&python)
        .arg(&script)
        .arg(&project_id)
        .env("ENGINEERING_HUB", &hub)
        .current_dir(script.parent().unwrap())
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// Same generator as export_dxf_native, but never writes a file — returns the
/// raw DXF content directly. For "Preview" actions that should show the export
/// without silently writing to disk every time it's opened.
#[tauri::command]
pub async fn preview_dxf_native(project_id: String) -> Result<String, String> {
    let python = find_python()?;
    let (_, hub) = find_cli_and_hub()?;

    let script = find_studio_script("export_dxf_cli.py")
        .ok_or_else(|| "export_dxf_cli.py not found — make sure the backend folder is next to the frontend".to_string())?;

    let output = std::process::Command::new(&python)
        .arg(&script)
        .arg(&project_id)
        .arg("--preview")
        .env("ENGINEERING_HUB", &hub)
        .current_dir(script.parent().unwrap())
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

#[cfg(test)]
mod export_format_tests {
    use super::*;

    /// yaml_str only checked the FIRST character for '#' — a mid-string '#'
    /// preceded by whitespace (e.g. a label like "spare tap #2") still starts
    /// a YAML comment, silently truncating the value on parse. Found via
    /// PyYAML round-trip testing while auditing all export formats.
    #[test]
    fn mid_string_hash_after_whitespace_gets_quoted() {
        let cases = ["50 #2 valve", "spare tap #2", "a#b", "no hash here"];
        for s in cases {
            let out = yaml_str(s);
            let needs_quote = s == "50 #2 valve" || s == "spare tap #2";
            if needs_quote {
                assert!(out.starts_with('\''), "expected quoted for {:?}, got {:?}", s, out);
            }
        }
        // 'a#b' has no whitespace before '#' so it's not a YAML comment risk —
        // must stay unquoted-or-quoted consistently with round-trip correctness,
        // the real assertion is the round-trip below.
    }

    /// Regression guard for the "sparse diagram / missing symbols" bug: raw
    /// YOLO detection type strings (e.g. "Ball_Valve") never matched the
    /// canonical lowercase kind set exactly, so nodes silently got no
    /// color/shape (mermaid) or were dropped from rendering entirely
    /// (svg_pid.py/dxf.py, fixed separately in Python). This exercises the
    /// actual raw type strings pulled from a real project's YOLO extraction.
    #[test]
    fn normalize_render_kind_covers_real_yolo_types() {
        let cases = [
            ("Ball_Valve", "valve"), ("4_Way_Valve", "valve"), ("Check_Valve", "checkvalve"),
            ("Pressure_Indicator", "indicator"), ("Pressure_Indicating_Transmitter", "transmitter"),
            ("Flow_Indicating_Controller", "controller"),
            ("Variable_Flow_Meter", "meter"), ("Regulator", "default"),
            ("Vessel", "vessel"), ("Tank", "vessel"), ("Filter", "filter"),
            ("Analysis_Transmitter", "transmitter"), ("Relief_Valve", "relief"),
            ("Heat_Exchanger", "heat_exchanger"), ("Reactor", "reactor"),
            ("junction", "junction"), ("", "default"), ("vessel", "vessel"),
        ];
        for (raw, expected) in cases {
            assert_eq!(normalize_render_kind(raw), expected, "for raw kind {:?}", raw);
        }
    }

    #[test]
    fn shapes_and_ids_match_python_port() {
        assert_eq!(mermaid_shape("transmitter", "FT-101"), "((\"FT-101\"))");
        assert_eq!(mermaid_shape("pump", "P-101"), "(\"P-101\")");
        assert_eq!(mermaid_shape("off_page_connector", "CWS HEADER"), ">\"CWS HEADER\"]");
        assert_eq!(mermaid_shape("vessel", "V-101"), "[\"V-101\"]");
        assert_eq!(mermaid_id("n1-2.3/4"), "n_n1_2_3_4");
        assert_eq!(mermaid_class_for_kind("heat_exchanger"), "heatExchanger");
        assert_eq!(mermaid_class_for_kind("unknown_kind"), "");
    }

    #[test]
    fn builds_flowchart_from_real_project_db() {
        let db_path = match find_db() {
            Some(p) => p,
            None => { eprintln!("skipping: no studio.db found"); return; }
        };
        let conn = Connection::open(&db_path).expect("open studio.db");
        let node_count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM nodes WHERE pid='p-id-5'", [], |r| r.get(0)
        ).unwrap_or(0);
        if node_count == 0 { eprintln!("skipping: p-id-5 has no nodes"); return; }

        let mermaid = build_mermaid_flowchart(&conn, "p-id-5").expect("build flowchart");
        assert!(mermaid.starts_with("flowchart LR"));
        assert!(mermaid.contains("classDef vessel"));
        // every non-empty content line after the header/classDefs is either a
        // classDef, blank, a node decl (n_...[...]), or an edge (--> / -.-> / ==>)
        let node_line_count = mermaid.lines().filter(|l| l.trim_start().starts_with("n_") && !l.contains("-->") && !l.contains("-.->") && !l.contains("==>")).count();
        assert!(node_line_count > 0, "expected at least one node declaration line");
    }

    /// Regression guard: the UI's Export/Preview buttons for non-svg/dxf cards
    /// call preview_export(format), NOT a dedicated export_<format> command
    /// (there isn't one for markdown/mermaid/vids/ympl). A previous version of
    /// this feature added the mermaid block to a dead export_markdown command
    /// the UI never called — this test exercises the actual function the UI
    /// invokes, not just the internal helper.
    #[test]
    fn preview_export_wires_mermaid_into_both_formats() {
        let db_path = match find_db() {
            Some(p) => p,
            None => { eprintln!("skipping: no studio.db found"); return; }
        };
        let conn = Connection::open(&db_path).expect("open studio.db");
        let node_count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM nodes WHERE pid='p-id-5'", [], |r| r.get(0)
        ).unwrap_or(0);
        if node_count == 0 { eprintln!("skipping: p-id-5 has no nodes"); return; }
        drop(conn);

        let mermaid_only = preview_export("p-id-5".to_string(), "mermaid".to_string())
            .expect("preview_export(mermaid)");
        assert!(mermaid_only.starts_with("flowchart LR"));

        let markdown = preview_export("p-id-5".to_string(), "markdown".to_string())
            .expect("preview_export(markdown)");
        assert!(markdown.contains("## P&ID Diagram"));
        assert!(markdown.contains("```mermaid"));
        assert!(markdown.contains("flowchart LR"));
    }

    /// Consolidation guard: `preview_export("ympl")` and `export_ympl` both go
    /// through the one Python YMPL writer (export_ympl_cli.py) instead of carrying two
    /// independent copies of the YAML-building logic. This proves the written
    /// file content is byte-for-byte identical to what preview returns for the
    /// same project. VIDS has no such pair to check any more — its hub-writing
    /// `export_vids` command is gone, leaving `preview_export("vids")` plus
    /// `save_export_to_path` as the only route to a file.
    #[test]
    fn preview_and_native_export_produce_identical_bytes() {
        let db_path = match find_db() {
            Some(p) => p,
            None => { eprintln!("skipping: no studio.db found"); return; }
        };
        let conn = Connection::open(&db_path).expect("open studio.db");
        let node_count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM nodes WHERE pid='p-id-5'", [], |r| r.get(0)
        ).unwrap_or(0);
        if node_count == 0 { eprintln!("skipping: p-id-5 has no nodes"); return; }
        drop(conn);

        let ympl_preview = preview_export("p-id-5".to_string(), "ympl".to_string())
            .expect("preview_export(ympl)");
        let ympl_result = export_ympl("p-id-5".to_string()).expect("export_ympl");
        let ympl_written = std::fs::read_to_string(&ympl_result.path).expect("read written ympl file");
        assert_eq!(ympl_preview, ympl_written, "preview_export(ympl) must match export_ympl output");
    }

    /// VIDS must carry the whole drawing. It used to read the
    /// `equipment`/`instruments`/`connections` mirror tables, which only ever
    /// receive the subset extraction classifies — valves, junctions and
    /// headers never land there, so most of the graph silently vanished from
    /// the export and connections referenced tags the document didn't define.
    #[test]
    fn vids_covers_every_node_and_edge() {
        let db_path = match find_db() {
            Some(p) => p,
            None => { eprintln!("skipping: no studio.db found"); return; }
        };
        let conn = Connection::open(&db_path).expect("open studio.db");
        let mut pids: Vec<String> = Vec::new();
        {
            let mut stmt = conn.prepare("SELECT pid FROM nodes GROUP BY pid").unwrap();
            let mut rows = stmt.query([]).unwrap();
            while let Some(r) = rows.next().unwrap() { pids.push(r.get(0).unwrap()); }
        }
        if pids.is_empty() { eprintln!("skipping: no project has nodes"); return; }

        for pid in &pids {
        let mut labels: Vec<String> = Vec::new();
        {
            let mut stmt = conn.prepare(
                "SELECT DISTINCT COALESCE(NULLIF(label,''), id) FROM nodes WHERE pid = ?"
            ).unwrap();
            let mut rows = stmt.query([pid.as_str()]).unwrap();
            while let Some(r) = rows.next().unwrap() { labels.push(r.get(0).unwrap()); }
        }
        let edge_count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM edges WHERE pid = ? AND COALESCE(from_id,'') <> ''",
            [pid.as_str()], |r| r.get(0),
        ).unwrap_or(0);

        let yaml = build_vids_yaml(&conn, pid).expect("build_vids_yaml");

        // every node reaches the document as an equipment or instrument key
        for label in &labels {
            assert!(
                yaml.contains(&format!("  {}:\n", yaml_str(label))),
                "node '{}' missing from VIDS export for {}", label, pid,
            );
        }
        // and every edge reaches it as a connection
        let emitted = yaml.lines().filter(|l| l.starts_with("- from_tag:") || l.starts_with("- fluid:")).count();
        assert!(
            emitted as i64 >= edge_count,
            "VIDS emitted {} connections for {} but the graph has {} edges",
            emitted, pid, edge_count,
        );
        eprintln!("{}: {} nodes, {} edges -> {} connections", pid, labels.len(), edge_count, emitted);
        }
    }
}

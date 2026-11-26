//! Plant hierarchy (site > plant > unit > area > system > subsystem) for the
//! desktop app. The tables are shared with the Python backend
//! (backend/services/hierarchy.py) and defined identically in schema.rs and
//! adapters/db.py.

use serde_json::{json, Value};
use std::collections::HashMap;

use crate::database::open_db;

/// The hierarchy as a nested tree with direct and total node counts, plus the
/// number of nodes not assigned anywhere.
#[tauri::command]
pub fn get_hierarchy(project_id: String) -> Result<Value, String> {
    let conn = open_db()?;
    let mut stmt = conn
        .prepare("SELECT id, parent_id, level, name FROM hierarchy WHERE pid = ? ORDER BY id")
        .map_err(|e| format!("Prepare hierarchy: {}", e))?;
    let rows: Vec<(i64, i64, String, String)> = stmt
        .query_map([project_id.as_str()], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .collect();

    let mut counts: HashMap<i64, i64> = HashMap::new();
    {
        let mut c = conn
            .prepare("SELECT hierarchy_id, COUNT(*) FROM node_hierarchy WHERE pid = ? GROUP BY hierarchy_id")
            .map_err(|e| e.to_string())?;
        let it = c
            .query_map([project_id.as_str()], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?)))
            .map_err(|e| e.to_string())?;
        for (hid, n) in it.filter_map(Result::ok) {
            counts.insert(hid, n);
        }
    }

    let mut children: HashMap<i64, Vec<i64>> = HashMap::new();
    let mut info: HashMap<i64, (String, String)> = HashMap::new();
    for (id, parent, level, name) in &rows {
        children.entry(*parent).or_default().push(*id);
        info.insert(*id, (level.clone(), name.clone()));
    }

    fn build(id: i64, info: &HashMap<i64, (String, String)>, children: &HashMap<i64, Vec<i64>>,
             counts: &HashMap<i64, i64>) -> (Value, i64) {
        let (level, name) = info.get(&id).cloned().unwrap_or_default();
        let direct = *counts.get(&id).unwrap_or(&0);
        let mut total = direct;
        let mut kids = Vec::new();
        for c in children.get(&id).cloned().unwrap_or_default() {
            let (v, t) = build(c, info, children, counts);
            total += t;
            kids.push(v);
        }
        (json!({"id": id, "level": level, "name": name, "direct_nodes": direct,
                "total_nodes": total, "children": kids}), total)
    }

    let roots: Vec<Value> = rows
        .iter()
        .filter(|(_, parent, _, _)| !info.contains_key(parent))
        .map(|(id, _, _, _)| build(*id, &info, &children, &counts).0)
        .collect();

    let unassigned: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM nodes n WHERE n.pid = ?1 AND NOT EXISTS \
             (SELECT 1 FROM node_hierarchy h WHERE h.pid = n.pid AND h.node_id = n.id)",
            [project_id.as_str()],
            |r| r.get(0),
        )
        .unwrap_or(0);
    Ok(json!({"roots": roots, "unassigned_nodes": unassigned}))
}

/// node id -> hierarchy entry id, for filtering the Canvas by system.
#[tauri::command]
pub fn get_node_hierarchy(project_id: String) -> Result<Value, String> {
    let conn = open_db()?;
    let mut stmt = conn
        .prepare("SELECT node_id, hierarchy_id FROM node_hierarchy WHERE pid = ?")
        .map_err(|e| e.to_string())?;
    let mut out = serde_json::Map::new();
    let it = stmt
        .query_map([project_id.as_str()], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))
        .map_err(|e| e.to_string())?;
    for (nid, hid) in it.filter_map(Result::ok) {
        out.insert(nid, json!(hid));
    }
    Ok(Value::Object(out))
}

/// Assign one node to a hierarchy entry, or clear it with hierarchy_id = None.
#[tauri::command]
pub fn assign_node_hierarchy(project_id: String, node_id: String, hierarchy_id: Option<i64>)
    -> Result<(), String>
{
    let conn = open_db()?;
    match hierarchy_id {
        Some(hid) => conn
            .execute(
                "INSERT INTO node_hierarchy (pid, node_id, hierarchy_id) VALUES (?1, ?2, ?3) \
                 ON CONFLICT(pid, node_id) DO UPDATE SET hierarchy_id = excluded.hierarchy_id",
                rusqlite::params![project_id, node_id, hid],
            )
            .map_err(|e| format!("Assign hierarchy: {}", e))?,
        None => conn
            .execute("DELETE FROM node_hierarchy WHERE pid = ?1 AND node_id = ?2",
                     rusqlite::params![project_id, node_id])
            .map_err(|e| format!("Clear hierarchy: {}", e))?,
    };
    Ok(())
}

/// Create (or find) a system and subsystem under an optional area. Idempotent,
/// like backend/services/hierarchy.py ensure_path.
#[tauri::command]
pub fn create_subsystem(project_id: String, system: String, subsystem: String, area: Option<String>)
    -> Result<i64, String>
{
    let conn = open_db()?;
    let mut parent: i64 = 0;
    let mut path: Vec<(&str, String)> = Vec::new();
    if let Some(a) = area.filter(|a| !a.trim().is_empty()) {
        path.push(("area", a));
    }
    path.push(("system", system));
    path.push(("subsystem", subsystem));
    for (level, name) in path {
        let name = name.trim().to_string();
        if name.is_empty() {
            return Err(format!("{} name is required", level));
        }
        let existing: Option<i64> = conn
            .query_row(
                "SELECT id FROM hierarchy WHERE pid = ?1 AND parent_id = ?2 AND level = ?3 \
                 AND lower(name) = lower(?4)",
                rusqlite::params![project_id, parent, level, name],
                |r| r.get(0),
            )
            .ok();
        parent = match existing {
            Some(id) => id,
            None => {
                conn.execute(
                    "INSERT INTO hierarchy (pid, parent_id, level, name, extra_json) \
                     VALUES (?1, ?2, ?3, ?4, '{}')",
                    rusqlite::params![project_id, parent, level, name],
                )
                .map_err(|e| format!("Create {}: {}", level, e))?;
                conn.last_insert_rowid()
            }
        };
    }
    Ok(parent)
}

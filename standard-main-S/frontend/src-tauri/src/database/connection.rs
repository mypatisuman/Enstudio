use rusqlite::Connection;

use super::paths::find_db;

pub fn open_db() -> Result<Connection, String> {
    let path = find_db().ok_or_else(|| "No studio.db found".to_string())?;
    Connection::open(&path).map_err(|e| format!("Cannot open {}: {}", path, e))
}

/// Generic over the row-mapper's output type `T` — existing callers whose
/// closures build `serde_json::Value` keep working unchanged (T is inferred
/// as Value), while new callers can map rows directly into a typed DTO.
pub fn collect_rows<P, F, T>(
    stmt: &mut rusqlite::Statement,
    params: P,
    f: F,
) -> Result<Vec<T>, String>
where
    P: rusqlite::Params,
    F: Fn(&rusqlite::Row) -> rusqlite::Result<T>,
{
    let rows = stmt
        .query_map(params, f)
        .map_err(|e| format!("Query failed: {}", e))?;
    let mut out = Vec::new();
    for r in rows {
        match r {
            Ok(v) => out.push(v),
            Err(e) => eprintln!("[collect_rows] row error: {}", e),
        }
    }
    Ok(out)
}

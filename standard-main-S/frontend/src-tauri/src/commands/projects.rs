use crate::database::{open_db, project_dir, collect_rows};
use crate::models::{CreateProjectResponse, ProjectStatsDto, ProjectSummaryDto, RenameProjectResponse, SuccessResponse};

fn slugify(name: &str) -> String {
    // lowercase, replace non-alphanumeric with hyphen, collapse runs, trim edges
    let mut slug = String::new();
    let mut last_hyphen = true; // leading hyphen suppression
    for c in name.to_lowercase().chars() {
        if c.is_alphanumeric() {
            slug.push(c);
            last_hyphen = false;
        } else if !last_hyphen {
            slug.push('-');
            last_hyphen = true;
        }
    }
    if slug.ends_with('-') { slug.pop(); }
    if slug.is_empty() { slug = "project".to_string(); }
    slug
}

#[tauri::command]
pub fn create_project(name: String, user_id: Option<i64>) -> Result<CreateProjectResponse, String> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err("Project name cannot be empty".to_string());
    }
    // An ownerless project would be invisible the moment it was created, since
    // list_projects filters strictly on user_id. The frontend passes
    // storedUserId(), which returns null once the 20-minute idle timeout has
    // elapsed — so this fires in the window between the session expiring and
    // AuthContext's 60-second sweep logging the user out. Failing loudly beats
    // creating a project the user can never open again.
    let user_id = user_id.ok_or("Your session has expired — please sign in again.")?;

    let conn     = open_db()?;
    let base_pid = slugify(&name);

    // Ensure unique pid
    let mut pid    = base_pid.clone();
    let mut suffix = 2u32;
    loop {
        let exists: i64 = conn
            .query_row("SELECT COUNT(*) FROM projects WHERE id=?", [pid.as_str()], |r| r.get(0))
            .unwrap_or(0);
        if exists == 0 { break; }
        pid = format!("{}-{}", base_pid, suffix);
        suffix += 1;
    }

    // INSERT into projects — title and plant_name hold the human name
    conn.execute(
        "INSERT INTO projects (id, title, plant_name, created, status, user_id)
         VALUES (?, ?, ?, datetime('now'), 'pending', ?)",
        rusqlite::params![pid, name, name, user_id],
    ).map_err(|e| format!("INSERT projects failed: {}", e))?;

    // Create project directory tree under the hub
    let proj_dir = project_dir(&pid).ok_or("No studio.db found")?;
    for sub in &["source_docs", "cache", "exports"] {
        std::fs::create_dir_all(proj_dir.join(sub))
            .map_err(|e| format!("Cannot create {}/{}: {}", pid, sub, e))?;
    }

    Ok(CreateProjectResponse { pid, name })
}

#[tauri::command]
pub fn get_project_stats(project_id: String) -> Result<ProjectStatsDto, String> {
    let conn = open_db()?;
    let pid  = project_id.as_str();
    let node_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM nodes WHERE pid=?", [pid], |r| r.get(0))
        .unwrap_or(0);
    let edge_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM edges WHERE pid=?", [pid], |r| r.get(0))
        .unwrap_or(0);
    Ok(ProjectStatsDto {
        node_count,
        // Phase 7: this used to report `edges + connections`. The canvas renders
        // ONLY the `edges` table -- the label-keyed `connections` JOIN was
        // removed because it produced a cartesian product of false edges when a
        // label like "Ball_Valve" matched many nodes (see get_graph). So the
        // Overview claimed "158 edges" for p-id-1 while the canvas drew 102,
        // which reads as 56 connections having been silently dropped.
        //
        // Report what the application can actually render.
        edge_count,
    })
}

#[tauri::command]
pub fn list_projects(user_id: Option<i64>) -> Result<Vec<ProjectSummaryDto>, String> {
    let conn = open_db()?;
    let mut stmt = conn.prepare(
        "SELECT p.id,
                COALESCE(p.title, p.plant_name, p.id) AS name,
                CASE
                    -- No drawing was ever uploaded/extracted, but there's real
                    -- content — it was authored entirely via Describe chat,
                    -- not extracted from a PDF, so it shouldn't read as such.
                    WHEN (SELECT COUNT(*) FROM sources WHERE pid = p.id) = 0
                     AND ((SELECT COUNT(*) FROM instruments WHERE pid = p.id) > 0
                          OR (SELECT COUNT(*) FROM equipment WHERE pid = p.id) > 0)
                    THEN 'described'
                    WHEN (SELECT COUNT(*) FROM instruments WHERE pid = p.id) > 0
                     AND (SELECT COUNT(*) FROM instruments i LEFT JOIN review r ON r.pid = i.pid AND r.key = i.tag WHERE i.pid = p.id AND COALESCE(r.state, 'pending') = 'pending') = 0
                    THEN 'reviewed'
                    WHEN (SELECT COUNT(*) FROM instruments WHERE pid = p.id) > 0 THEN 'extracted'
                    WHEN (SELECT COUNT(*) FROM sources WHERE pid = p.id) > 0 THEN 'uploaded'
                    ELSE COALESCE(p.status, 'pending')
                END AS status,
                (SELECT COUNT(*) FROM instruments WHERE pid = p.id) AS instruments,
                (SELECT COUNT(*) FROM equipment  WHERE pid = p.id) AS equipment,
                (SELECT COUNT(*) FROM sources    WHERE pid = p.id) AS drawings,
                p.last_extraction,
                p.last_activity
         FROM projects p
         -- Strictly the signed-in user's projects. Unowned rows are NOT shown.
         -- That is only safe because ownership is guaranteed at both ends:
         -- create_project rejects a missing user_id, and adopt_orphan_projects()
         -- in schema.rs assigns any pre-existing/CLI-created orphan at startup.
         -- Loosen this and you get cross-user leakage; drop those two guards and
         -- you get silently invisible projects. Both halves are load-bearing.
         WHERE p.user_id = ?
         ORDER BY p.id",
    ).map_err(|e| format!("Prepare failed: {}", e))?;

    collect_rows(&mut stmt, [user_id], |row| {
        Ok(ProjectSummaryDto {
            id:          row.get::<_, String>(0)?,
            name:        row.get::<_, String>(1)?,
            status:      row.get::<_, String>(2)?,
            instruments: row.get::<_, i64>(3)?,
            equipment:   row.get::<_, i64>(4)?,
            drawings:    row.get::<_, i64>(5)?,
            last_extraction: row.get::<_, Option<String>>(6)?,
            last_activity:   row.get::<_, Option<String>>(7)?,
        })
    })
}

#[tauri::command]
pub fn rename_project(project_id: String, new_name: String) -> Result<RenameProjectResponse, String> {
    let new_name = new_name.trim().to_string();
    if new_name.is_empty() {
        return Err("Project name cannot be empty".to_string());
    }

    let mut conn = open_db()?;
    let base_pid = slugify(&new_name);

    // Duplicate check
    let exists: i64 = conn
        .query_row("SELECT COUNT(*) FROM projects WHERE (id=? OR title=?) AND id!=?", 
                   [base_pid.as_str(), new_name.as_str(), project_id.as_str()], |r| r.get(0))
        .unwrap_or(0);
    if exists > 0 {
        return Err("A project with this name already exists.".to_string());
    }

    let old_pid = project_id.as_str();
    let new_pid = base_pid.as_str();

    // 1. Rename the physical folder if pid changed
    if old_pid != new_pid {
        if let (Some(old_dir), Some(new_dir)) = (project_dir(old_pid), project_dir(new_pid)) {
            if old_dir.exists() {
                std::fs::rename(&old_dir, &new_dir)
                    .map_err(|e| format!("Failed to rename folder: {}", e))?;
            }
        }
    }

    // 2. Begin a transaction for deep DB rename
    let tx = conn.transaction().map_err(|e| e.to_string())?;

    tx.execute_batch("PRAGMA defer_foreign_keys = ON;").unwrap_or(());

    // Update main project row
    tx.execute(
        "UPDATE projects SET id=?, title=?, plant_name=? WHERE id=?",
        [new_pid, new_name.as_str(), new_name.as_str(), old_pid]
    ).map_err(|e| format!("Failed to update project: {}", e))?;

    // If pid changed, cascade to all related tables
    if old_pid != new_pid {
        let tables = [
            "sources", "equipment", "instruments", "nodes", "edges", "connections", "review",
            "exports", "loops", "canvas_positions", "cache_entries", "cache_manifest", "proposals",
            "describe_sessions", "describe_messages",
        ];
        for table in tables.iter() {
            let sql = format!("UPDATE {} SET pid=? WHERE pid=?", table);
            tx.execute(&sql, [new_pid, old_pid]).ok(); // ignore errors if table doesn't exist or is empty
        }
    }

    tx.commit().map_err(|e| e.to_string())?;

    Ok(RenameProjectResponse { success: true, new_id: new_pid.to_string(), new_name })
}

/// Every table that references projects(id). Child rows must be removed
/// before the project row or the FOREIGN KEY constraint fails.
///
/// ORDER MATTERS, and not only relative to `projects`. `sources` is itself a
/// parent: nodes.source_id and edges.source_id both REFERENCE sources(id). It
/// used to sit second in this list, so deleting any project that had been
/// extracted failed at "Failed clearing sources: FOREIGN KEY constraint
/// failed" — the rows pointing at it had not been removed yet. It now comes
/// last. Anything added here that references sources must go above it.
/// This list is checked against the database's own foreign keys by
/// `every_table_referencing_projects_is_listed` below — add a table with a
/// `pid` FK and forget it here, and that test fails rather than the user's
/// delete. `activity_log` was exactly that case: missing, so the child loop
/// succeeded and the bare `DELETE FROM projects` failed instead, producing an
/// unprefixed "FOREIGN KEY constraint failed" that named no table at all.
const CHILD_TABLES: &[&str] = &[
    "review", "exports", "connections", "edges", "nodes",
    "instruments", "equipment", "loops", "canvas_positions",
    "cache_entries", "cache_manifest", "proposals",
    "describe_messages", "describe_sessions", "activity_log",
    "grid_positions", "describe_pending", "describe_session_states",
    // node_hierarchy references hierarchy, so it is cleared first.
    "node_hierarchy", "hierarchy",
    "geometry_junctions", "geometry_lines", "geometry_pages",
    "sources",
];

#[tauri::command]
pub fn delete_project(project_id: String) -> Result<SuccessResponse, String> {
    let mut conn = open_db()?;
    let pid = project_id.clone();

    let tx = conn.transaction().map_err(|e| e.to_string())?;
    for tbl in CHILD_TABLES {
        // Ignore "no such table" so a missing optional table doesn't abort the delete.
        if let Err(e) = tx.execute(&format!("DELETE FROM {} WHERE pid = ?", tbl), [pid.as_str()]) {
            let msg = e.to_string();
            if !msg.contains("no such table") {
                return Err(format!("Failed clearing {}: {}", tbl, msg));
            }
        }
    }
    tx.execute("DELETE FROM projects WHERE id = ?", [pid.as_str()])
        .map_err(|e| e.to_string())?;
    tx.commit().map_err(|e| e.to_string())?;

    // Delete physical project directory under the hub
    if let Some(proj_dir) = project_dir(&pid) {
        let _ = std::fs::remove_dir_all(proj_dir);
    }

    Ok(SuccessResponse { success: true })
}

#[cfg(test)]
mod ownership_visibility_tests {
    /// Listing is strictly by owner. The safety of that depends entirely on
    /// every project HAVING an owner — see adopt_orphan_projects() in
    /// schema.rs and the create_project guard.
    const VISIBLE: &str = "SELECT id FROM projects WHERE user_id = ? ORDER BY id";

    fn db(users: &[i64]) -> rusqlite::Connection {
        let c = rusqlite::Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE users (id INTEGER PRIMARY KEY);
             CREATE TABLE projects (id TEXT PRIMARY KEY, user_id INTEGER);
             INSERT INTO projects VALUES ('mine-a', 2);
             INSERT INTO projects VALUES ('mine-b', 2);
             INSERT INTO projects VALUES ('orphan', NULL);
             INSERT INTO projects VALUES ('theirs', 9);"
        ).unwrap();
        for u in users {
            c.execute("INSERT INTO users (id) VALUES (?)", [u]).unwrap();
        }
        c
    }

    fn visible_to(c: &rusqlite::Connection, uid: i64) -> Vec<String> {
        let mut s = c.prepare(VISIBLE).unwrap();
        let rows = s.query_map([uid], |r| r.get::<_, String>(0)).unwrap();
        rows.filter_map(|r| r.ok()).collect()
    }

    /// Mirror of adopt_orphan_projects() in schema.rs. Kept in step with it —
    /// the listing query above is only safe while this keeps orphans at zero.
    fn adopt(c: &rusqlite::Connection) {
        let users: i64 = c.query_row("SELECT COUNT(*) FROM users", [], |r| r.get(0)).unwrap();
        if users != 1 { return; }
        c.execute("UPDATE projects SET user_id = (SELECT id FROM users LIMIT 1) WHERE user_id IS NULL", []).unwrap();
    }

    #[test]
    fn listing_is_strictly_by_owner() {
        let c = db(&[2]);
        // Before adoption the orphan is invisible — that is the whole reason
        // adopt_orphan_projects() has to run at startup.
        assert_eq!(visible_to(&c, 2), vec!["mine-a", "mine-b"]);
        assert!(!visible_to(&c, 2).contains(&"theirs".to_string()));
    }

    #[test]
    fn sole_user_adopts_orphans_so_nothing_stays_hidden() {
        let c = db(&[2]);
        adopt(&c);
        assert_eq!(visible_to(&c, 2), vec!["mine-a", "mine-b", "orphan"]);
        let left: i64 = c.query_row("SELECT COUNT(*) FROM projects WHERE user_id IS NULL", [], |r| r.get(0)).unwrap();
        assert_eq!(left, 0, "no project may be left ownerless");
    }

    #[test]
    fn multiple_users_means_no_arbitrary_adoption() {
        // With two accounts there is no defensible owner, so the orphan stays
        // unassigned rather than being handed to whoever happens to be first.
        let c = db(&[2, 9]);
        adopt(&c);
        assert!(!visible_to(&c, 2).contains(&"orphan".to_string()));
        assert!(!visible_to(&c, 9).contains(&"orphan".to_string()));
    }

    #[test]
    fn users_never_see_each_others_projects() {
        let c = db(&[2, 9]);
        adopt(&c);
        assert_eq!(visible_to(&c, 2), vec!["mine-a", "mine-b"]);
        assert_eq!(visible_to(&c, 9), vec!["theirs"]);
    }
}

#[cfg(test)]
mod phase7_stats_tests {
    //! Phase 7 -- the Overview edge count must match what the canvas draws.

    fn db_with(edges: usize, connections: usize) -> rusqlite::Connection {
        let c = rusqlite::Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE nodes (id TEXT, pid TEXT, PRIMARY KEY (id, pid));
             CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT,
                                 from_id TEXT, to_id TEXT);
             CREATE TABLE connections (id TEXT, pid TEXT, from_tag TEXT, to_tag TEXT,
                                 PRIMARY KEY (id, pid));",
        ).unwrap();
        for i in 0..edges {
            c.execute("INSERT INTO edges (pid, from_id, to_id) VALUES ('P', ?, ?)",
                      rusqlite::params![format!("n{}", i), format!("n{}", i + 1)]).unwrap();
        }
        for i in 0..connections {
            c.execute("INSERT INTO connections (id, pid, from_tag, to_tag) VALUES (?, 'P', 'A', 'B')",
                      [format!("c{}", i)]).unwrap();
        }
        c
    }

    /// Mirrors the query get_project_stats runs. Kept as a direct query because
    /// the command itself resolves the hub database, which a unit test has no
    /// business pointing at.
    fn edge_count(c: &rusqlite::Connection) -> i64 {
        c.query_row("SELECT COUNT(*) FROM edges WHERE pid=?", ["P"], |r| r.get(0)).unwrap()
    }

    #[test]
    fn stats_edge_count_excludes_the_connections_table() {
        // p-id-1's real shape: 102 renderable edges, 56 legacy tag connections.
        let c = db_with(102, 56);
        assert_eq!(edge_count(&c), 102,
            "Overview must report renderable edges, not edges + connections");
        let legacy: i64 = c
            .query_row("SELECT COUNT(*) FROM connections WHERE pid=?", ["P"], |r| r.get(0))
            .unwrap();
        assert_eq!(legacy, 56, "fixture sanity");
        assert_ne!(edge_count(&c), 102 + legacy,
            "the summed count is what this test exists to prevent");
    }

    #[test]
    fn stats_edge_count_matches_when_there_are_no_connections() {
        let c = db_with(7, 0);
        assert_eq!(edge_count(&c), 7);
    }
}

#[cfg(test)]
mod delete_order_tests {
    /// The schema is the authority on what has to be cleared. Read the real
    /// foreign keys and require every table pointing at projects(id) to be in
    /// CHILD_TABLES — `activity_log` was missing, and the symptom was a bare
    /// "FOREIGN KEY constraint failed" on the final DELETE that named nothing.
    #[test]
    fn every_table_referencing_projects_is_listed() {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        conn.execute_batch(crate::database::schema::SCHEMA_SQL)
            .expect("schema applies to a fresh database");

        let tables: Vec<String> = {
            let mut s = conn.prepare(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).unwrap();
            let v = s.query_map([], |r| r.get(0)).unwrap().map(|x| x.unwrap()).collect();
            v
        };

        let mut unlisted = Vec::new();
        for t in &tables {
            let mut s = conn.prepare(&format!("PRAGMA foreign_key_list({})", t)).unwrap();
            let refs: Vec<String> = s.query_map([], |r| r.get::<_, String>(2))
                .unwrap().map(|x| x.unwrap()).collect();
            if refs.iter().any(|target| target == "projects")
                && !super::CHILD_TABLES.contains(&t.as_str()) {
                unlisted.push(t.clone());
            }
        }
        assert!(unlisted.is_empty(),
                "these tables reference projects(id) but delete_project never clears them: {:?}",
                unlisted);
    }

    /// Reproduces the real failure: a project with an extracted node, deleted
    /// with foreign keys enforced. `sources` ahead of `nodes` in CHILD_TABLES
    /// is what produced "Failed clearing sources: FOREIGN KEY constraint failed".
    #[test]
    fn deleting_a_project_with_sources_and_nodes_succeeds() {
        let mut conn = rusqlite::Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "PRAGMA foreign_keys = ON;
             CREATE TABLE projects (id TEXT PRIMARY KEY);
             CREATE TABLE sources  (id INTEGER PRIMARY KEY, pid TEXT REFERENCES projects(id));
             CREATE TABLE nodes    (id TEXT, pid TEXT REFERENCES projects(id),
                                    source_id INTEGER REFERENCES sources(id));
             CREATE TABLE edges    (id INTEGER PRIMARY KEY, pid TEXT REFERENCES projects(id),
                                    source_id INTEGER REFERENCES sources(id));
             INSERT INTO projects VALUES ('P');
             INSERT INTO sources  VALUES (1,'P');
             INSERT INTO nodes    VALUES ('n1','P',1);
             INSERT INTO edges    VALUES (1,'P',1);",
        ).unwrap();

        // Same sequence delete_project uses, restricted to the tables that exist here.
        let order: Vec<&str> = super::CHILD_TABLES.iter().copied()
            .filter(|t| matches!(*t, "sources" | "nodes" | "edges")).collect();
        assert_eq!(order, vec!["edges", "nodes", "sources"],
                   "sources must be cleared after the tables referencing it");

        let tx = conn.transaction().unwrap();
        for tbl in &order {
            tx.execute(&format!("DELETE FROM {} WHERE pid = ?", tbl), ["P"])
              .unwrap_or_else(|e| panic!("clearing {} failed: {}", tbl, e));
        }
        tx.execute("DELETE FROM projects WHERE id = ?", ["P"]).unwrap();
        tx.commit().unwrap();

        let left: i64 = conn.query_row("SELECT COUNT(*) FROM projects", [], |r| r.get(0)).unwrap();
        assert_eq!(left, 0, "project row survived the delete");
    }
}

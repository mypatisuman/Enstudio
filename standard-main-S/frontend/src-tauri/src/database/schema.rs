use super::paths::{find_db, read_env_hub};

/// Row origin ('authored' / 'extracted'), maintained by the database: insert
/// triggers copy the extra_json marker into the `origin` column for every
/// writer, and the UPDATEs backfill older rows. Identical text lives in
/// backend/adapters/db.py ORIGIN_SQL; backend/tests/test_schema_parity.py
/// fails if they differ.
pub(crate) const ORIGIN_SQL: &str = r#"
CREATE INDEX IF NOT EXISTS idx_nodes_pid_origin ON nodes(pid, origin);
CREATE INDEX IF NOT EXISTS idx_edges_pid_origin ON edges(pid, origin);
CREATE TRIGGER IF NOT EXISTS trg_nodes_origin AFTER INSERT ON nodes
WHEN NEW.origin IS NULL
BEGIN
  UPDATE nodes SET origin = CASE WHEN
      NEW.extra_json LIKE '%"origin": "authored"%' OR NEW.extra_json LIKE '%"origin":"authored"%'
      OR NEW.extra_json LIKE '%"source": "describe_agent"%' OR NEW.extra_json LIKE '%"source":"describe_agent"%'
    THEN 'authored' ELSE 'extracted' END
  WHERE rowid = NEW.rowid;
END;
CREATE TRIGGER IF NOT EXISTS trg_edges_origin AFTER INSERT ON edges
WHEN NEW.origin IS NULL
BEGIN
  UPDATE edges SET origin = CASE WHEN
      NEW.extra_json LIKE '%"origin": "authored"%' OR NEW.extra_json LIKE '%"origin":"authored"%'
      OR NEW.extra_json LIKE '%"drawing": "DESCRIBE"%' OR NEW.extra_json LIKE '%"drawing":"DESCRIBE"%'
    THEN 'authored' ELSE 'extracted' END
  WHERE rowid = NEW.rowid;
END;
UPDATE nodes SET origin = CASE WHEN
    extra_json LIKE '%"origin": "authored"%' OR extra_json LIKE '%"origin":"authored"%'
    OR extra_json LIKE '%"source": "describe_agent"%' OR extra_json LIKE '%"source":"describe_agent"%'
  THEN 'authored' ELSE 'extracted' END
WHERE origin IS NULL;
UPDATE edges SET origin = CASE WHEN
    extra_json LIKE '%"origin": "authored"%' OR extra_json LIKE '%"origin":"authored"%'
    OR extra_json LIKE '%"drawing": "DESCRIBE"%' OR extra_json LIKE '%"drawing":"DESCRIBE"%'
  THEN 'authored' ELSE 'extracted' END
WHERE origin IS NULL;
"#;

pub(crate) const SCHEMA_SQL: &str = "
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name     TEXT NOT NULL,
  username      TEXT,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',
  status        TEXT NOT NULL DEFAULT 'active',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  last_login    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE TABLE IF NOT EXISTS projects (
  id                TEXT PRIMARY KEY,
  title             TEXT,
  company           TEXT,
  process_type      TEXT,
  created           TEXT,
  plant_name        TEXT,
  revision          INTEGER,
  extraction_locked INTEGER DEFAULT 0,
  last_extraction   TEXT,
  last_activity     TEXT,
  status            TEXT,
  stats_json        TEXT,
  user_id           INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS sources (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pid       TEXT REFERENCES projects(id),
  filename  TEXT,
  file_hash TEXT,
  uploaded  TEXT,
  cached    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS exports (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  pid      TEXT REFERENCES projects(id),
  type     TEXT,
  filename TEXT,
  exported TEXT
);
CREATE TABLE IF NOT EXISTS nodes (
  id          TEXT,
  pid         TEXT REFERENCES projects(id),
  kind        TEXT,
  kind_detail TEXT,
  label       TEXT,
  area        TEXT,
  x           REAL,
  y           REAL,
  extra_json  TEXT,
  source_id   INTEGER REFERENCES sources(id),
  origin      TEXT,
  PRIMARY KEY (id, pid)
);
CREATE TABLE IF NOT EXISTS edges (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pid        TEXT REFERENCES projects(id),
  from_id    TEXT,
  to_id      TEXT,
  kind       TEXT,
  label      TEXT,
  extra_json TEXT,
  source_id  INTEGER REFERENCES sources(id),
  origin     TEXT
);
CREATE TABLE IF NOT EXISTS instruments (
  tag           TEXT,
  pid           TEXT REFERENCES projects(id),
  area          TEXT,
  kind_detail   TEXT,
  type          TEXT,
  equipment_ref TEXT,
  extra_json    TEXT,
  PRIMARY KEY (tag, pid)
);
CREATE TABLE IF NOT EXISTS equipment (
  tag         TEXT,
  pid         TEXT REFERENCES projects(id),
  area        TEXT,
  kind_detail TEXT,
  type        TEXT,
  extra_json  TEXT,
  PRIMARY KEY (tag, pid)
);
CREATE TABLE IF NOT EXISTS connections (
  id         TEXT,
  pid        TEXT REFERENCES projects(id),
  from_tag   TEXT,
  to_tag     TEXT,
  type       TEXT,
  extra_json TEXT,
  PRIMARY KEY (id, pid)
);
CREATE TABLE IF NOT EXISTS loops (
  loop_id   TEXT,
  pid       TEXT REFERENCES projects(id),
  loop_json TEXT,
  PRIMARY KEY (loop_id, pid)
);
CREATE TABLE IF NOT EXISTS review (
  pid   TEXT REFERENCES projects(id),
  key   TEXT,
  state TEXT,
  PRIMARY KEY (pid, key)
);
CREATE TABLE IF NOT EXISTS canvas_positions (
  pid     TEXT REFERENCES projects(id),
  node_id TEXT,
  x       REAL,
  y       REAL,
  PRIMARY KEY (pid, node_id)
);
CREATE TABLE IF NOT EXISTS cache_entries (
  pid       TEXT REFERENCES projects(id),
  cache_key TEXT,
  data_json TEXT,
  PRIMARY KEY (pid, cache_key)
);
CREATE TABLE IF NOT EXISTS cache_manifest (
  pid          TEXT REFERENCES projects(id),
  scan_json    TEXT,
  total_tokens INTEGER DEFAULT 0,
  total_cost   REAL    DEFAULT 0.0,
  last_scan    TEXT,
  PRIMARY KEY (pid)
);
CREATE TABLE IF NOT EXISTS proposals (
  pid          TEXT REFERENCES projects(id),
  node_id      TEXT,
  type         TEXT,
  original     TEXT,
  proposed     TEXT,
  confidence   REAL,
  method       TEXT,
  review_state TEXT,
  extra_json   TEXT,
  PRIMARY KEY (pid, node_id, type)
);
CREATE TABLE IF NOT EXISTS describe_sessions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pid        TEXT REFERENCES projects(id),
  title      TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS activity_log (
  pid         TEXT REFERENCES projects(id),
  stage       TEXT,
  label       TEXT,
  detail      TEXT,
  status      TEXT,
  started_at  INTEGER,
  duration_ms INTEGER,
  indent      INTEGER DEFAULT 0,
  updated_at  TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (pid, stage)
);
CREATE TABLE IF NOT EXISTS describe_messages (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id        INTEGER REFERENCES describe_sessions(id),
  pid               TEXT REFERENCES projects(id),
  role              TEXT,
  display           TEXT,
  api_content       TEXT,
  nodes_added       INTEGER DEFAULT 0,
  edges_added       INTEGER DEFAULT 0,
  nodes_updated     INTEGER DEFAULT 0,
  pending_deletes   TEXT,
  delete_resolution TEXT,
  nodes_deleted     INTEGER DEFAULT 0,
  is_error          INTEGER DEFAULT 0,
  created_at        TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grid_positions (
  pid      TEXT REFERENCES projects(id),
  node_id  TEXT,
  row_idx  INTEGER,
  col_idx  INTEGER,
  PRIMARY KEY (pid, node_id)
);
CREATE TABLE IF NOT EXISTS describe_session_states (
  pid                  TEXT REFERENCES projects(id),
  session_id           TEXT,
  history_json         TEXT,
  active_solution_json TEXT,
  updated_at           TEXT,
  PRIMARY KEY (pid, session_id)
);
CREATE TABLE IF NOT EXISTS describe_pending (
  pid        TEXT REFERENCES projects(id),
  session_id TEXT,
  data_json  TEXT,
  PRIMARY KEY (pid, session_id)
);
CREATE TABLE IF NOT EXISTS hierarchy (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pid        TEXT REFERENCES projects(id),
  parent_id  INTEGER NOT NULL DEFAULT 0,
  level      TEXT NOT NULL,
  name       TEXT NOT NULL,
  code       TEXT,
  extra_json TEXT,
  UNIQUE (pid, parent_id, level, name)
);
CREATE TABLE IF NOT EXISTS node_hierarchy (
  pid          TEXT REFERENCES projects(id),
  node_id      TEXT,
  hierarchy_id INTEGER REFERENCES hierarchy(id),
  PRIMARY KEY (pid, node_id)
);
CREATE TABLE IF NOT EXISTS geometry_pages (
  pid       TEXT REFERENCES projects(id),
  source_id INTEGER NOT NULL DEFAULT 0,
  page      INTEGER NOT NULL,
  width     INTEGER,
  height    INTEGER,
  PRIMARY KEY (pid, source_id, page)
);
CREATE TABLE IF NOT EXISTS geometry_lines (
  pid         TEXT REFERENCES projects(id),
  line_id     TEXT NOT NULL,
  source_id   INTEGER NOT NULL DEFAULT 0,
  page        INTEGER NOT NULL DEFAULT 1,
  type        TEXT,
  style       TEXT,
  direction   TEXT,
  points_json TEXT,
  PRIMARY KEY (pid, line_id)
);
CREATE TABLE IF NOT EXISTS geometry_junctions (
  pid         TEXT REFERENCES projects(id),
  junction_id TEXT NOT NULL,
  source_id   INTEGER NOT NULL DEFAULT 0,
  page        INTEGER NOT NULL DEFAULT 1,
  kind        TEXT,
  x           REAL,
  y           REAL,
  extra_json  TEXT,
  PRIMARY KEY (pid, junction_id)
);
";

/// Ensure the EngineeringHub folder exists and studio.db is initialised.
/// Called once at startup — safe to call when hub+DB already exist (no-ops).
pub fn ensure_hub_and_db() {
    // If DB already exists, just re-run the schema against it (idempotent —
    // every statement is CREATE TABLE IF NOT EXISTS) so new tables added by
    // app updates get picked up without a full hub re-init.
    if let Some(path) = find_db() {
        match rusqlite::Connection::open(&path) {
            Ok(conn) => {
                // Add the username column BEFORE the batch — SCHEMA_SQL's unique
                // index on users(username) would otherwise fail on an old table.
                migrate_users_username(&conn);
                // Add reset_token / reset_expires for the forgot-password flow.
                migrate_reset_token(&conn);
                // Phase 5: attribute nodes/edges to the document they came from.
                migrate_source_id(&conn);
                if let Err(e) = conn.execute_batch(SCHEMA_SQL) {
                    eprintln!("[ensure_hub_and_db] Schema update failed: {}", e);
                }
                migrate_origin(&conn);
                adopt_orphan_projects(&conn);
                // backfill_activity_log() removed by request — it reconstructed a
                // synthetic "Extraction complete" row for every already-extracted
                // project on EVERY startup, which kept refilling the feed right
                // after being cleared. The activity feed now only ever reflects
                // real live extraction events going forward.
            }
            Err(e) => eprintln!("[ensure_hub_and_db] Cannot open {}: {}", path, e),
        }
        return;
    }

    // Determine hub path: configured value or sensible default.
    let hub_path: std::path::PathBuf = if let Some(hub) = read_env_hub() {
        std::path::PathBuf::from(hub)
    } else {
        // Relative candidates (from the CWD when running `tauri dev` inside
        // frontend, `../../` resolves to the repo root).
        let rel_candidates = [
            "../../EngineeringHub/EngineeringHub",
            "../EngineeringHub/EngineeringHub",
            "EngineeringHub/EngineeringHub",
        ];
        let chosen = rel_candidates.iter()
            .map(std::path::PathBuf::from)
            .find(|p| p.parent().map_or(true, |par| {
                par.as_os_str().is_empty() || par.exists()
            }));
        chosen.unwrap_or_else(|| {
            // Absolute fallback: %USERPROFILE%\EngineeringHub\EngineeringHub
            let home = std::env::var("USERPROFILE")
                .or_else(|_| std::env::var("HOME"))
                .unwrap_or_else(|_| ".".to_string());
            std::path::PathBuf::from(home).join("EngineeringHub").join("EngineeringHub")
        })
    };

    // Create directory tree.
    if let Err(e) = std::fs::create_dir_all(&hub_path) {
        eprintln!("[ensure_hub_and_db] Cannot create hub dir {}: {}", hub_path.display(), e);
        return;
    }

    // Expose the path so read_env_hub() / find_db() succeed for this process.
    std::env::set_var("ENGINEERING_HUB", hub_path.to_string_lossy().as_ref());

    // Persist the path to ../backend/.env or backend/.env so future runs pick it up.
    let hub_str = hub_path.to_string_lossy().to_string();
    let env_candidates = ["../backend/.env", "../../backend/.env", "backend/.env"];
    for env_path in &env_candidates {
        let p = std::path::Path::new(env_path);
        // Only write if the parent directory exists.
        if p.parent().is_some_and(|d| d.exists()) {
            let line = format!("ENGINEERING_HUB={}\n", hub_str);
            // Append only if not already set, otherwise overwrite.
            let existing = std::fs::read_to_string(p).unwrap_or_default();
            let new_content = if existing.lines().any(|l| l.starts_with("ENGINEERING_HUB=")) {
                existing.lines()
                    .map(|l| if l.starts_with("ENGINEERING_HUB=") { line.trim_end().to_string() } else { l.to_string() })
                    .collect::<Vec<_>>()
                    .join("\n") + "\n"
            } else {
                format!("{}{}", existing, line)
            };
            let _ = std::fs::write(p, new_content);
            break;
        }
    }

    // Open (and implicitly create) studio.db, then run the schema.
    let db_path = hub_path.join("studio.db");
    match rusqlite::Connection::open(&db_path) {
        Err(e) => eprintln!("[ensure_hub_and_db] Cannot open DB {}: {}", db_path.display(), e),
        Ok(conn) => {
            migrate_users_username(&conn);   // no-op on a brand-new DB (no users table yet)
            migrate_reset_token(&conn);      // no-op on a brand-new DB
            if let Err(e) = conn.execute_batch(SCHEMA_SQL) {
                eprintln!("[ensure_hub_and_db] Schema init failed: {}", e);
            } else {
                migrate_origin(&conn);
                eprintln!("[ensure_hub_and_db] Hub ready at {}", hub_path.display());
            }
        }
    }
}

/// Give any ownerless project an owner, so `list_projects` — which filters
/// strictly on `user_id = ?` — never hides real work.
///
/// Orphans are produced by more than legacy data: `backend/extraction_cli`,
/// `repositories/project_repository.py` and `tools/migrate_to_sqlite.py` all
/// INSERT into `projects` without a `user_id`, so a project created outside the
/// desktop app arrives unowned. Without this, such a project holds its nodes,
/// edges and instruments but can never be opened again.
///
/// Only adopts when there is exactly ONE user account. With several accounts
/// there is no non-arbitrary owner, and silently handing one user's project to
/// another would be worse than leaving it hidden — so it is left alone and the
/// count is logged instead.
fn adopt_orphan_projects(conn: &rusqlite::Connection) {
    let orphans: i64 = conn
        .query_row("SELECT COUNT(*) FROM projects WHERE user_id IS NULL", [], |r| r.get(0))
        .unwrap_or(0);
    if orphans == 0 { return; }

    let users: i64 = conn
        .query_row("SELECT COUNT(*) FROM users", [], |r| r.get(0))
        .unwrap_or(0);
    if users != 1 {
        eprintln!(
            "[schema] {} project(s) have no owner and {} user accounts exist — \
             leaving them unassigned (they will not be listed). Set projects.user_id manually.",
            orphans, users
        );
        return;
    }

    match conn.execute(
        "UPDATE projects SET user_id = (SELECT id FROM users LIMIT 1) WHERE user_id IS NULL",
        [],
    ) {
        Ok(n)  => eprintln!("[schema] Adopted {} ownerless project(s) to the sole user account", n),
        Err(e) => eprintln!("[schema] Could not adopt ownerless projects: {}", e),
    }
}

/// Phase 5 — attach document identity to graph rows.
///
/// Additive only: `ALTER TABLE ADD COLUMN` on a nullable column rewrites no
/// existing row and cannot fail destructively. Rows written before this
/// migration keep `source_id = NULL`, meaning "legacy / unattributed", and
/// still load exactly as before. The primary key is deliberately NOT changed —
/// cross-document id uniqueness comes from the extraction-time id prefix, so
/// no table rebuild is required.
///
/// Errors are ignored the same way the migrations below do it: re-running on an
/// already-migrated database raises "duplicate column name".
fn migrate_source_id(conn: &rusqlite::Connection) {
    let _ = conn.execute("ALTER TABLE nodes ADD COLUMN source_id INTEGER REFERENCES sources(id)", []);
    let _ = conn.execute("ALTER TABLE edges ADD COLUMN source_id INTEGER REFERENCES sources(id)", []);
    for stmt in [
        "CREATE INDEX IF NOT EXISTS idx_nodes_pid_source ON nodes(pid, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_edges_pid_source ON edges(pid, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_edges_pid ON edges(pid)",
        "CREATE INDEX IF NOT EXISTS idx_sources_pid ON sources(pid)",
    ] {
        if let Err(e) = conn.execute(stmt, []) {
            eprintln!("[migrate_source_id] {}: {}", stmt, e);
        }
    }
}

/// Add the `origin` column to graph tables created before it existed, then
/// install the triggers and backfill (ORIGIN_SQL). Idempotent: the ALTERs fail
/// with "duplicate column name" once applied, and every other statement is
/// IF NOT EXISTS or limited to rows whose origin is still NULL.
fn migrate_origin(conn: &rusqlite::Connection) {
    let _ = conn.execute("ALTER TABLE nodes ADD COLUMN origin TEXT", []);
    let _ = conn.execute("ALTER TABLE edges ADD COLUMN origin TEXT", []);
    if let Err(e) = conn.execute_batch(ORIGIN_SQL) {
        eprintln!("[migrate_origin] {}", e);
    }
}

/// Add the `username` column to a pre-existing users table (no-op if present).
/// Fresh DBs already have it from SCHEMA_SQL; this only rescues DBs created
/// before username existed. The UNIQUE index lives in SCHEMA_SQL.
fn migrate_users_username(conn: &rusqlite::Connection) {
    // Errors with "duplicate column name" when it already exists — ignored.
    let _ = conn.execute("ALTER TABLE users ADD COLUMN username TEXT", []);

    // Case-insensitive uniqueness, matching username_taken() in commands/auth.rs.
    // SCHEMA_SQL's idx_users_username is case-SENSITIVE, so on its own it would
    // happily accept "Daman" alongside an existing "daman" — exactly the
    // collision the app-level check rejects.
    //
    // Kept out of the SCHEMA_SQL batch on purpose: execute_batch aborts at the
    // first failing statement, so if a legacy DB already holds two names
    // differing only by case, creating this index there would take every
    // CREATE TABLE after it down with it. Here a failure is isolated to this
    // one statement and the app still has its own check.
    let _ = conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_ci ON users(LOWER(username))",
        [],
    );
    let _ = conn.execute("ALTER TABLE projects ADD COLUMN user_id INTEGER REFERENCES users(id)", []);
    // Last real activity of any kind (extraction OR Describe edits) — kept
    // separate from last_extraction, which stays extraction-only so the
    // "Extracted N ago" label and the described/extracted status split don't
    // lie about a Describe-only project having been extracted.
    let _ = conn.execute("ALTER TABLE projects ADD COLUMN last_activity TEXT", []);
}

/// Add reset_token / reset_expires to users for the forgot-password flow.
/// Silently ignored if the columns already exist ("duplicate column" error).
fn migrate_reset_token(conn: &rusqlite::Connection) {
    let _ = conn.execute("ALTER TABLE users ADD COLUMN reset_token TEXT", []);
    let _ = conn.execute("ALTER TABLE users ADD COLUMN reset_expires TEXT", []);
}

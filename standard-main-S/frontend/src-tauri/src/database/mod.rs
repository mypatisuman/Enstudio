pub mod schema;
pub mod paths;
pub mod connection;

pub use paths::{find_db, project_dir, find_exports_dir,
                find_python, find_cli_and_hub, find_studio_script};
pub use connection::{open_db, collect_rows};
pub use paths::extraction_engine;
pub use schema::ensure_hub_and_db;

/// Serialises tests that repoint ENGINEERING_HUB.
///
/// That variable is process-global and cargo runs tests in parallel threads,
/// so two hub-swapping tests otherwise read each other's database. It has to
/// live here rather than per-module: separate locks in separate test modules
/// do not exclude each other, which is exactly how this was first written and
/// exactly why it failed.
#[cfg(test)]
pub static TEST_HUB_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

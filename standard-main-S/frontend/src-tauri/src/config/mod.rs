// Persistent app settings — stored in the `settings` key/value table in
// studio.db, the SAME database the Flask extraction pipeline's
// adapters/config.py reads/writes. Both must point at one store for "set it
// in Settings, it's used everywhere" to actually hold.
//
// Values for `*_api_key` fields are encrypted at rest (see secrets.rs).
// adapters/secrets.py implements the identical format so the Python
// extraction pipeline can read the rows this module writes.
use rusqlite::Connection;

use crate::database::find_db;

pub mod secrets;
use secrets::{decrypt_secret, encrypt_secret, is_secret_key};

fn open_settings_db() -> Result<Connection, String> {
    let path = find_db().ok_or("No studio.db found")?;
    let conn = Connection::open(&path).map_err(|e| e.to_string())?;
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ).map_err(|e| e.to_string())?;
    Ok(conn)
}

/// Reads a named string key from the `settings` table, decrypting it if it is
/// a credential field. A credential that fails to decrypt (DB copied from
/// another machine or another Windows user) reads as unset rather than
/// returning ciphertext that would later be sent to a provider as a key.
pub fn load_config_key(field: &str) -> Option<String> {
    let conn = open_settings_db().ok()?;
    let value: String = conn
        .query_row("SELECT value FROM settings WHERE key = ?1", [field], |r| r.get(0))
        .ok()?;
    if value.is_empty() { return None; }

    if !is_secret_key(field) { return Some(value); }
    match decrypt_secret(&value) {
        Ok(plain) if plain.is_empty() => None,
        Ok(plain) => Some(plain),
        Err(e) => {
            // Never log the value itself — only that it could not be read.
            eprintln!("[config] Cannot decrypt {}: {} — treating as unset", field, e);
            None
        }
    }
}

/// Upserts `field = value` into the `settings` table, encrypting the value
/// first if it is a credential field.
pub fn save_config_key(field: &str, value: &str) -> Result<std::path::PathBuf, String> {
    let path = find_db().ok_or_else(|| "No studio.db found".to_string())?;
    let conn = open_settings_db()?;
    let stored = if is_secret_key(field) { encrypt_secret(value)? } else { value.to_string() };
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?1, ?2) \
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        rusqlite::params![field, stored],
    ).map_err(|e| e.to_string())?;
    Ok(std::path::PathBuf::from(path))
}

/// Re-encrypt any `*_api_key` row still stored as plaintext. Called once at
/// startup so keys saved before encryption existed do not sit in the clear
/// forever — without this, an existing install keeps its plaintext key until
/// the user happens to retype it in Settings.
///
/// Returns the number of rows rewritten. Best-effort: a missing DB or an
/// unreadable row is skipped, never fatal to startup.
pub fn migrate_plaintext_secrets() -> usize {
    let Ok(conn) = open_settings_db() else { return 0 };

    let rows: Vec<(String, String)> = {
        let Ok(mut stmt) = conn.prepare("SELECT key, value FROM settings") else { return 0 };
        let Ok(mapped) = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        }) else { return 0 };
        mapped.filter_map(|r| r.ok()).collect()
    };

    let mut migrated = 0;
    for (key, value) in rows {
        if !is_secret_key(&key) || value.is_empty() { continue; }
        if value.starts_with(secrets::ENC_PREFIX) { continue; }   // already encrypted
        let Ok(enc) = encrypt_secret(&value) else { continue };
        if conn.execute(
            "UPDATE settings SET value = ?2 WHERE key = ?1",
            rusqlite::params![key, enc],
        ).is_ok() {
            migrated += 1;
        }
    }
    if migrated > 0 {
        eprintln!("[config] Encrypted {} plaintext API key(s) at rest", migrated);
    }
    migrated
}

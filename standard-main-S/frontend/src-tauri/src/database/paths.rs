/// Read ENGINEERING_HUB from a backend/.env file, if that file has one.
fn hub_from_env_file(path: &std::path::Path) -> Option<String> {
    let content = std::fs::read_to_string(path).ok()?;
    content.lines().find_map(|line| {
        let val = line.trim().strip_prefix("ENGINEERING_HUB=")?.trim();
        (!val.is_empty()).then(|| val.to_string())
    })
}

pub fn read_env_hub() -> Option<String> {
    if let Ok(hub) = std::env::var("ENGINEERING_HUB") {
        if !hub.is_empty() { return Some(hub); }
    }

    // CWD-relative — covers `cargo tauri dev` run from frontend/.
    for path in ["../backend/.env", "../../backend/.env", "backend/.env"] {
        if let Some(hub) = hub_from_env_file(std::path::Path::new(path)) {
            return Some(hub);
        }
    }

    // Exe-relative walk-up — covers an installed build, where the CWD is
    // whatever the shell happened to be. Replaces a hardcoded
    // C:\Users\User\Desktop\... path that only ever resolved on one machine.
    // Falls through to None on a fresh install, and ensure_hub_and_db() then
    // creates the hub under %USERPROFILE%.
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..6 {
            let Some(d) = dir else { break };
            if let Some(hub) = hub_from_env_file(&d.join("backend").join(".env")) {
                return Some(hub);
            }
            dir = d.parent().map(|p| p.to_path_buf());
        }
    }

    None
}

pub fn find_db() -> Option<String> {
    if let Some(hub) = read_env_hub() {
        let path = format!(r"{}\studio.db", hub.trim_end_matches('\\'));
        if std::path::Path::new(&path).exists() {
            return Some(path);
        }
    }
    None
}

/// True when `project_id` is a plain, non-traversing directory name.
///
/// `Path::join` DISCARDS the left-hand side when the right side is absolute
/// or drive-qualified, exactly like Python's pathlib:
///
///     Path::new(r"C:\hub\projects").join("..")         -> C:\hub\projects\..
///     Path::new(r"C:\hub\projects").join(r"C:\Windows") -> C:\Windows
///
/// `project_id` arrives from the webview over IPC, so it is untrusted input
/// on the same footing as an HTTP path parameter. Mirrors the allowlist in
/// backend/security.py::validate_pid so both halves of the app agree on what
/// a project id may be.
pub fn is_safe_project_id(project_id: &str) -> bool {
    if project_id.is_empty() || project_id.len() > 64 {
        return false;
    }
    // Must start with an alphanumeric or '_' — blocks ".", "..", dotfiles,
    // and "-flag"-shaped names.
    match project_id.chars().next() {
        Some(c) if c.is_ascii_alphanumeric() || c == '_' => {}
        _ => return false,
    }
    if !project_id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.') {
        return false;
    }
    // Windows reserved device names, with or without an extension.
    let stem = project_id.split('.').next().unwrap_or("").to_ascii_uppercase();
    const RESERVED: [&str; 8] = ["CON", "PRN", "AUX", "NUL", "COM1", "COM2", "LPT1", "LPT2"];
    !RESERVED.contains(&stem.as_str())
}

/// Resolve `{hub}/projects/{pid}` from the DB path. The one shared
/// implementation behind every command that used to re-derive this
/// independently via `find_db()` + `.parent()` + `.join("projects").join(pid)`.
///
/// Returns None for an unsafe `project_id`, so every caller that already
/// handles the "no studio.db" None case now also rejects traversal without
/// needing its own check.
pub fn project_dir(project_id: &str) -> Option<std::path::PathBuf> {
    if !is_safe_project_id(project_id) {
        eprintln!("[paths] rejected unsafe project_id: {:?}", project_id);
        return None;
    }
    let db_path = find_db()?;
    let hub = std::path::Path::new(&db_path).parent()?;
    Some(hub.join("projects").join(project_id))
}

pub fn find_exports_dir(project_id: &str) -> Option<std::path::PathBuf> {
    Some(project_dir(project_id)?.join("exports"))
}


pub fn find_python() -> Result<String, String> {
    for cmd in &["python", "python3", "py"] {
        if std::process::Command::new(cmd)
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return Ok((*cmd).to_string());
        }
    }
    Err("Python 3 not found in PATH — install Python 3.8+ and add it to PATH".to_string())
}

// Returns (cli_path, hub_dir_string)
/// Which extraction engine the desktop app runs.
///
/// "classic"  -> backend/extract_cli.py   (the CV + LLM-verification pipeline)
/// "agentic"  -> backend/run_agentic.py   (the LangGraph multi-agent pipeline)
///
/// Both emit the same NDJSON progress contract on stdout and accept the same
/// positional arguments plus `--source-id` / `--llm-only`, so `run_extraction`
/// drives either one unchanged.
///
/// Resolved from the STUDIO_EXTRACTION_ENGINE environment variable first, then
/// the `extraction_engine` settings key, defaulting to "classic" so an
/// existing install's behaviour does not change until someone opts in.
pub fn extraction_engine() -> String {
    if let Ok(v) = std::env::var("STUDIO_EXTRACTION_ENGINE") {
        let v = v.trim().to_lowercase();
        if v == "classic" || v == "agentic" {
            return v;
        }
    }
    match crate::config::load_config_key("extraction_engine") {
        Some(v) => {
            let v = v.trim().to_lowercase();
            if v == "agentic" { "agentic".to_string() } else { "classic".to_string() }
        }
        None => "classic".to_string(),
    }
}

/// Returns (script_path, hub_dir_string) for the configured engine.
pub fn find_cli_and_hub() -> Result<(std::path::PathBuf, String), String> {
    let db_path = find_db().ok_or_else(|| "No studio.db found".to_string())?;
    let hub = std::path::Path::new(&db_path)
        .parent()
        .ok_or_else(|| "Cannot determine hub dir".to_string())?;
    // hub   = .../EngineeringHub/EngineeringHub
    // root  = two parents up = repo root
    let repo = hub.parent().and_then(|p| p.parent())
        .ok_or_else(|| "Cannot determine repo root from hub path".to_string())?;

    let engine = extraction_engine();
    let script_name = if engine == "agentic" { "run_agentic.py" } else { "extract_cli.py" };
    let cli = repo.join("backend").join(script_name);
    if !cli.exists() {
        // Fall back to the classic entry point rather than failing outright:
        // a missing agentic script must not make extraction impossible.
        let fallback = repo.join("backend").join("extract_cli.py");
        if engine == "agentic" && fallback.exists() {
            eprintln!("[extraction] {} not found at {} - falling back to extract_cli.py",
                      script_name, cli.display());
            return Ok((fallback, hub.to_string_lossy().to_string()));
        }
        return Err(format!("{} not found at {}", script_name, cli.display()));
    }
    Ok((cli, hub.to_string_lossy().to_string()))
}

pub fn find_studio_script(name: &str) -> Option<std::path::PathBuf> {
    // 1. Walk up from the executable.
    //    Dev layout:  .../frontend/src-tauri/target/debug/<exe>
    //                 4 levels up → repo root → backend/
    //    Release:     same structure via `cargo tauri build`
    if let Ok(exe) = std::env::current_exe() {
        let exe_dir = exe.parent().map(|p| p.to_path_buf());
        let mut dir = exe_dir;
        for levels in 1u8..=6 {
            if let Some(ref d) = dir {
                let candidate = d.join("backend").join(name);
                if candidate.exists() {
                    return Some(candidate);
                }
                if levels < 6 {
                    dir = d.parent().map(|p| p.to_path_buf());
                }
            }
        }
    }

    // 2. CWD-relative (works when running `cargo tauri dev` from frontend/)
    for base in &["../backend", "../../backend", "backend"] {
        let p = std::path::Path::new(base).join(name);
        if p.exists() {
            return Some(p);
        }
    }

    // 3. Absolute path via ENGINEERING_HUB env var — try multiple ancestor levels
    if let Some(hub_str) = read_env_hub() {
        let mut dir: Option<std::path::PathBuf> = Some(std::path::PathBuf::from(&hub_str));
        for _ in 0..5 {
            dir = dir.and_then(|d| d.parent().map(|p| p.to_path_buf()));
            if let Some(ref d) = dir {
                let p = d.join("backend").join(name);
                if p.exists() {
                    return Some(p);
                }
            }
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::{hub_from_env_file, is_safe_project_id};
    use std::io::Write;

    /// project_id crosses the IPC boundary from the webview and is then
    /// joined onto the hub path. Every shape below either escapes that
    /// directory or names a Windows device, so all must be rejected.
    #[test]
    fn project_id_allowlist_blocks_traversal() {
        for ok in ["daman", "p-id-5", "Project_1", "a", "x.y", "9lives"] {
            assert!(is_safe_project_id(ok), "should accept {:?}", ok);
        }
        for bad in [
            "", ".", "..", "../x", "a/b", "a\\b", "C:", "C:/Windows",
            r"\\srv\share", ".hidden", "-flag", "CON", "nul.txt", "a b",
            "a:b", "a*b", "a\0b",
        ] {
            assert!(!is_safe_project_id(bad), "should reject {:?}", bad);
        }
        // 64 is the cap, 65 is over it.
        assert!(is_safe_project_id(&"a".repeat(64)));
        assert!(!is_safe_project_id(&"a".repeat(65)));
    }

    /// The .env parser has to skip comments, blank lines, and unrelated keys,
    /// and tolerate a missing file — it is the only thing standing between an
    /// installed build and "No studio.db found" now that the hardcoded
    /// developer path is gone.
    #[test]
    fn parses_hub_line_and_ignores_everything_else() {
        let dir = std::env::temp_dir().join("enstudio_paths_test");
        std::fs::create_dir_all(&dir).unwrap();

        let good = dir.join("good.env");
        let mut f = std::fs::File::create(&good).unwrap();
        writeln!(f, "# comment\n\nANTHROPIC_API_KEY=sk-xxx\nENGINEERING_HUB=C:\\hub\\EngineeringHub\nOTHER=1").unwrap();
        assert_eq!(hub_from_env_file(&good).as_deref(), Some(r"C:\hub\EngineeringHub"));

        // Key present but empty → treated as unset, not as an empty hub path.
        let empty = dir.join("empty.env");
        std::fs::write(&empty, "ENGINEERING_HUB=\n").unwrap();
        assert_eq!(hub_from_env_file(&empty), None);

        // Key absent entirely, and a file that does not exist at all.
        let none = dir.join("none.env");
        std::fs::write(&none, "OTHER=1\n").unwrap();
        assert_eq!(hub_from_env_file(&none), None);
        assert_eq!(hub_from_env_file(&dir.join("missing.env")), None);

        let _ = std::fs::remove_dir_all(&dir);
    }
}

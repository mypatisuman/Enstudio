mod database;
mod config;
mod state;
mod models;
mod utils;
mod commands;

use state::{ProcessState, CredentialsState};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(ProcessState::new())
        .manage(CredentialsState::new())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Auto-create EngineeringHub folder + studio.db on first run.
            database::ensure_hub_and_db();
            // Then re-encrypt any API key still stored in the clear from
            // before at-rest encryption existed. Must run after the DB is
            // guaranteed to exist, hence here rather than in CredentialsState.
            config::migrate_plaintext_secrets();
            // Seed SMTP settings from env vars into the settings table on first run.
            // Only writes a key if the env var is set AND the settings table doesn't
            // already have a value for it, so manual edits in Settings are never
            // clobbered on restart.
            seed_smtp_from_env();

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::auth::signup_request,
            commands::auth::signup_verify_otp,
            commands::auth::signup_finalize,
            commands::auth::check_email,
            commands::auth::check_username,
            commands::auth::login,
            commands::auth::get_user,
            commands::auth::update_user,
            commands::auth::forgot_password,
            commands::auth::verify_otp,
            commands::auth::check_new_password,
            commands::auth::reset_password,
            commands::review::get_node_kinds,
            commands::misc::get_source_data_url,
            commands::misc::get_page_image_path,
            commands::misc::read_attachment,
            commands::export::export_dxf_native,
            commands::export::preview_dxf_native,
            commands::projects::list_projects,
            commands::projects::create_project,
            commands::projects::get_project_stats,
            commands::review::get_instruments,
            commands::review::get_equipment,
            commands::export::get_export_status,
            commands::export::get_export_content,
            commands::export::preview_export,
            commands::export::fetch_svg_export,
            commands::export::open_path_in_os,
            commands::export::save_export_to_path,
            commands::export::export_project,
            commands::review::get_gaps,
            commands::graph::delete_node,
            commands::projects::rename_project,
            commands::projects::delete_project,
            commands::ingest::get_sources,
            commands::ingest::delete_source,
            commands::ingest::native_upload_file,
            commands::ingest::upload_pdf,
            commands::extraction::run_extraction,
            commands::misc::get_usage_history,
            commands::misc::delete_project_usage,
            commands::misc::delete_usage_scan,
            commands::misc::add_usage_scan,
            commands::extraction::cancel_extraction,
            commands::llm_config::save_api_key,
            commands::llm_config::get_api_key_status,
            commands::llm_config::get_models,
            commands::llm_config::save_models,
            commands::llm_config::save_gemini_key,
            commands::llm_config::get_gemini_model,
            commands::llm_config::save_gemini_model,
            commands::llm_config::save_openai_key,
            commands::llm_config::get_openai_model,
            commands::llm_config::save_openai_model,
            commands::llm_config::get_llm_provider,
            commands::llm_config::save_llm_provider,
            commands::llm_config::get_custom_providers,
            commands::llm_config::save_custom_provider,
            commands::llm_config::remove_custom_provider,
            // Phase 0: the four `get_*_key` commands that returned plaintext
            // credentials to the webview are gone. The renderer now asks the
            // proxy to make the call, or asks for a boolean.
            commands::llm_proxy::llm_complete,
            commands::llm_proxy::get_credential_status,
            commands::graph::batch_insert_nodes,
            commands::graph::batch_insert_junctions,
            commands::graph::batch_insert_edges,
            commands::graph::update_node_by_tag,
            commands::graph::delete_node_by_tag,
            commands::describe::list_describe_sessions,
            commands::describe::create_describe_session,
            commands::describe::get_describe_messages,
            commands::describe::save_describe_message,
            commands::describe::resolve_describe_delete,
            commands::describe::rename_describe_session,
            commands::describe::delete_describe_session,
            commands::describe::describe_agent_turn,
            commands::describe::describe_agent_resolve,
            commands::hierarchy::get_hierarchy,
            commands::hierarchy::get_node_hierarchy,
            commands::hierarchy::assign_node_hierarchy,
            commands::hierarchy::create_subsystem,
            commands::graph::import_llm_verified,
            commands::graph::update_node,
            commands::graph::update_node_position,
            commands::graph::delete_edge,
            commands::graph::delete_edge_by_id,
            commands::graph::insert_edge_by_id,
            commands::graph::update_edge_bend,
            commands::graph::clear_edge_bend,
            commands::ingest::reextract_source,
            commands::graph::get_graph,
            commands::misc::get_edge_paths,
            commands::export::export_ympl,
            commands::export::export_connectivity,
            commands::export::preview_connectivity,
            commands::review::update_review_status,
            commands::review::bulk_update_review,
            commands::review::update_instrument,
            commands::review::add_connection,
            commands::review::delete_instrument,
            commands::misc::debug_db,
            commands::activity::save_activity_entry,
            commands::activity::get_activity_log,
            commands::activity::clear_activity_log,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// On first run, copy SMTP_* environment variables into the `settings` table so
/// the forgot-password email sender finds credentials without any extra UI step.
/// Only inserts a row when the key is NOT already present — existing values
/// (set via Settings or a previous run) are never overwritten.
fn seed_smtp_from_env() {
    let mut env_content = String::new();
    // Look for the backend/.env file in the same places paths.rs does
    for path in ["../backend/.env", "../../backend/.env", "backend/.env"] {
        if let Ok(c) = std::fs::read_to_string(path) {
            env_content = c;
            break;
        }
    }

    if env_content.is_empty() { return; }

    let pairs: &[(&str, &str)] = &[
        ("smtp_host",     "SMTP_HOST="),
        ("smtp_port",     "SMTP_PORT="),
        ("smtp_user",     "SMTP_USER="),
        ("smtp_password", "SMTP_PASSWORD="),
        ("smtp_from",     "SMTP_FROM="),
    ];

    for line in env_content.lines() {
        let line = line.trim();
        if line.starts_with('#') || line.is_empty() { continue; }
        
        for &(db_key, prefix) in pairs {
            if let Some(val) = line.strip_prefix(prefix) {
                let val = val.trim();
                if !val.is_empty() && config::load_config_key(db_key).is_none() {
                    let _ = config::save_config_key(db_key, val);
                }
            }
        }
    }
}

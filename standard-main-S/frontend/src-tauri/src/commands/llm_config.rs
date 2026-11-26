use serde_json::{json, Value};

use crate::config::{load_config_key, save_config_key};

use crate::state::CredentialsState;

/// Persist the API key to the settings table in studio.db AND update memory.
#[tauri::command]
pub fn save_api_key(state: tauri::State<'_, CredentialsState>, key: String) -> Value {
    *state.api_key.lock().unwrap() = key.clone();
    match save_config_key("anthropic_api_key", &key) {
        Ok(path) => json!({ "ok": true, "path": path.to_string_lossy() }),
        Err(e)   => json!({ "ok": false, "error": e }),
    }
}

#[tauri::command]
pub fn get_api_key_status(state: tauri::State<'_, CredentialsState>) -> Value {
    let key = state.api_key.lock().unwrap();
    json!({ "set": !key.is_empty() })
}

// REMOVED (Phase 0): get_api_key / get_gemini_key / get_openai_key /
// get_custom_provider_key returned plaintext provider credentials to the
// webview. Nothing needs the value there any more — the renderer asks
// llm_proxy::llm_complete to make the call, and uses
// llm_proxy::get_credential_status when it only needs to know whether a key
// exists. Do not reintroduce a getter that returns a secret.

#[tauri::command]
pub fn get_models() -> Value {
    let anthropic = load_config_key("anthropic_model_smart").unwrap_or_else(|| "claude-sonnet-4-6".to_string());
    json!({
        "anthropic": anthropic
    })
}

#[tauri::command]
pub fn save_models(anthropic: String) -> Value {
    let _ = save_config_key("anthropic_model_smart", &anthropic);
    json!({ "success": true })
}

#[tauri::command]
pub fn save_gemini_key(state: tauri::State<'_, CredentialsState>, key: String) -> Value {
    *state.gemini_key.lock().unwrap() = key.clone();
    match save_config_key("gemini_api_key", &key) {
        Ok(path) => json!({ "ok": true, "path": path.to_string_lossy() }),
        Err(e)   => json!({ "ok": false, "error": e }),
    }
}

#[tauri::command]
pub fn get_gemini_model() -> Value {
    let smart = load_config_key("gemini_model_smart").unwrap_or_else(|| "gemini-2.0-flash".to_string());
    json!({ "gemini": smart })
}

#[tauri::command]
pub fn save_gemini_model(model: String) -> Value {
    let _ = save_config_key("gemini_model_smart", &model);
    json!({ "success": true })
}

#[tauri::command]
pub fn save_openai_key(state: tauri::State<'_, CredentialsState>, key: String) -> Value {
    *state.openai_key.lock().unwrap() = key.clone();
    match save_config_key("openai_api_key", &key) {
        Ok(path) => json!({ "ok": true, "path": path.to_string_lossy() }),
        Err(e)   => json!({ "ok": false, "error": e }),
    }
}

#[tauri::command]
pub fn get_openai_model() -> Value {
    let smart = load_config_key("openai_model_smart").unwrap_or_else(|| "gpt-5.5".to_string());
    json!({ "openai": smart })
}

#[tauri::command]
pub fn save_openai_model(model: String) -> Value {
    let _ = save_config_key("openai_model_smart", &model);
    json!({ "success": true })
}

// ── Custom (named-preset) providers ─────────────────────────────────────────
// Presets (Grok, DeepSeek, Mistral, Groq, OpenRouter, Together...) live only
// in the frontend + adapters/llm_presets.py; the backend just stores whatever
// id/key/model the frontend hands it under a small set of `custom_<id>_*`
// keys, plus one JSON array (`custom_providers`) of which ids are active.

fn get_custom_provider_ids() -> Vec<String> {
    load_config_key("custom_providers")
        .and_then(|s| serde_json::from_str::<Vec<String>>(&s).ok())
        .unwrap_or_default()
}

fn save_custom_provider_ids(ids: &[String]) -> Result<(), String> {
    let json = serde_json::to_string(ids).map_err(|e| e.to_string())?;
    save_config_key("custom_providers", &json)?;
    Ok(())
}

#[tauri::command]
pub fn get_custom_providers() -> Value {
    let list: Vec<Value> = get_custom_provider_ids().iter().map(|id| {
        let model = load_config_key(&format!("custom_{}_model", id)).unwrap_or_default();
        let has_key = load_config_key(&format!("custom_{}_api_key", id)).is_some();
        json!({ "id": id, "model": model, "hasKey": has_key })
    }).collect();
    json!(list)
}

#[tauri::command]
pub fn save_custom_provider(id: String, api_key: String, model: String) -> Value {
    let mut ids = get_custom_provider_ids();
    if !ids.contains(&id) {
        ids.push(id.clone());
        if let Err(e) = save_custom_provider_ids(&ids) {
            return json!({ "ok": false, "error": e });
        }
    }
    if !api_key.is_empty() {
        if let Err(e) = save_config_key(&format!("custom_{}_api_key", id), &api_key) {
            return json!({ "ok": false, "error": e });
        }
    }
    if let Err(e) = save_config_key(&format!("custom_{}_model", id), &model) {
        return json!({ "ok": false, "error": e });
    }
    json!({ "ok": true })
}

#[tauri::command]
pub fn remove_custom_provider(id: String) -> Value {
    let ids: Vec<String> = get_custom_provider_ids().into_iter().filter(|i| i != &id).collect();
    match save_custom_provider_ids(&ids) {
        Ok(_)  => json!({ "ok": true }),
        Err(e) => json!({ "ok": false, "error": e }),
    }
}

#[tauri::command]
pub fn get_llm_provider() -> String {
    load_config_key("llm_provider").unwrap_or_else(|| "anthropic".to_string())
}

#[tauri::command]
pub fn save_llm_provider(provider: String) -> Value {
    match save_config_key("llm_provider", &provider) {
        Ok(_)  => json!({ "ok": true }),
        Err(e) => json!({ "ok": false, "error": e }),
    }
}

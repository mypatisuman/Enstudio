// LLM egress proxy — the ONLY place a provider API key leaves this process.
//
// Before this module, DescribeScreen and the Copilot fetched the plaintext
// key into the webview (`get_api_key`, `get_gemini_key`, …) and called
// api.anthropic.com / api.openai.com / generativelanguage.googleapis.com
// directly from the renderer. Combined with `"csp": null` that made any
// script-injection bug in the webview a credential-exfiltration bug.
//
// Now the renderer sends provider + messages and gets back text + usage. The
// key is read from CredentialsState (populated at startup from the
// DPAPI-encrypted `settings` table) and never crosses the IPC boundary.
//
// This deliberately mirrors the request shapes that were already in
// src/features/describe/utils/llmClient.ts rather than inventing a second
// LLM abstraction — same endpoints, same bodies, same cost tables. The TS
// `callLlm` is now a thin invoke() wrapper over this command, so there is
// still exactly one LLM client on the frontend side.
//
// ponytail: non-streaming only. The Copilot's Anthropic SSE path used to
// stream token-by-token; it now receives the whole reply at once, the same
// way it already did for gemini/openai. Restoring real streaming means
// emitting Tauri events from a reader thread here (the pattern
// extraction.rs already uses for NDJSON) — do that if token-by-token
// output matters more than the extra moving part.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::config::load_config_key;
use crate::state::CredentialsState;

const ANTHROPIC_URL: &str = "https://api.anthropic.com/v1/messages";
const OPENAI_URL: &str = "https://api.openai.com/v1/chat/completions";

const DEFAULT_ANTHROPIC_MODEL: &str = "claude-sonnet-4-6";
const DEFAULT_GEMINI_MODEL: &str = "gemini-2.0-flash";
const DEFAULT_OPENAI_MODEL: &str = "gpt-5.5";

const MAX_TOKENS: u32 = 8000;

// Mirrors CUSTOM_PROVIDER_PRESETS in src/domain/llm/customProviderPresets.ts
// and adapters/llm_presets.py. Kept as a fixed allowlist rather than taking
// a base URL from the renderer: an attacker-controlled URL here would turn
// this command into an SSRF primitive that also attaches a real API key.
fn custom_preset_base_url(preset_id: &str) -> Option<&'static str> {
    match preset_id {
        "grok" => Some("https://api.x.ai/v1"),
        "deepseek" => Some("https://api.deepseek.com/v1"),
        "mistral" => Some("https://api.mistral.ai/v1"),
        "groq" => Some("https://api.groq.com/openai/v1"),
        "openrouter" => Some("https://openrouter.ai/api/v1"),
        "together" => Some("https://api.together.xyz/v1"),
        _ => None,
    }
}

// ── Wire types ──────────────────────────────────────────────────────────────

/// One message from the renderer. `content` is either a plain string or the
/// typed part array Describe uses for image/PDF attachments — same shape as
/// `ApiMessage` in llmClient.ts, passed through untouched.
#[derive(Debug, Deserialize)]
pub struct ProxyMessage {
    pub role: String,
    pub content: Value,
}

#[derive(Debug, Serialize)]
pub struct ProxyUsage {
    #[serde(rename = "tokensIn")]
    pub tokens_in: i64,
    #[serde(rename = "tokensOut")]
    pub tokens_out: i64,
    pub provider: String,
    pub model: String,
    #[serde(rename = "costUsd")]
    pub cost_usd: f64,
}

#[derive(Debug, Serialize)]
pub struct ProxyResponse {
    pub text: String,
    pub usage: ProxyUsage,
}

// ── Cost tables (mirror llmClient.ts / adapters/llm_*.py) ───────────────────

fn cost_per_mtok(provider: &str, model: &str) -> (f64, f64) {
    match provider {
        "anthropic" => match model {
            "claude-sonnet-4-6" => (3.00, 15.00),
            "claude-haiku-4-5-20251001" => (0.25, 1.25),
            "claude-opus-4-7" => (15.00, 75.00),
            _ => (3.00, 15.00),
        },
        "gemini" => match model {
            "gemini-2.0-flash" => (0.075, 0.30),
            "gemini-2.0-flash-lite" => (0.0375, 0.15),
            "gemini-2.5-flash" => (0.15, 0.60),
            "gemini-2.5-flash-lite" => (0.075, 0.30),
            "gemini-2.5-pro" => (1.25, 10.00),
            "gemini-1.5-pro" => (1.25, 5.00),
            "gemini-1.5-flash" => (0.075, 0.30),
            _ => (0.075, 0.30),
        },
        // openai and every custom preset bill through the OpenAI table.
        _ => match model {
            "gpt-4o" => (2.50, 10.00),
            "gpt-4o-mini" => (0.15, 0.60),
            "gpt-4.1" => (2.00, 8.00),
            "gpt-4.1-mini" => (0.40, 1.60),
            _ => (5.00, 20.00),
        },
    }
}

fn estimate_cost(provider: &str, model: &str, tin: i64, tout: i64) -> f64 {
    let (rin, rout) = cost_per_mtok(provider, model);
    let raw = (tin as f64 * rin + tout as f64 * rout) / 1_000_000.0;
    (raw * 1_000_000.0).round() / 1_000_000.0
}

// ── Content translation (mirrors toAnthropicContent / toGeminiParts / toOpenAiContent) ──

fn to_anthropic_content(content: &Value) -> Value {
    let Some(parts) = content.as_array() else { return content.clone() };
    Value::Array(parts.iter().map(|p| {
        match p.get("type").and_then(|t| t.as_str()) {
            Some("text") => json!({ "type": "text", "text": p.get("text").cloned().unwrap_or_default() }),
            Some("image") => json!({ "type": "image", "source": {
                "type": "base64",
                "media_type": p.get("mediaType").cloned().unwrap_or_default(),
                "data": p.get("data").cloned().unwrap_or_default() } }),
            _ => json!({ "type": "document", "source": {
                "type": "base64",
                "media_type": p.get("mediaType").cloned().unwrap_or_default(),
                "data": p.get("data").cloned().unwrap_or_default() } }),
        }
    }).collect())
}

fn to_gemini_parts(content: &Value) -> Value {
    if let Some(s) = content.as_str() {
        return json!([{ "text": s }]);
    }
    let Some(parts) = content.as_array() else { return json!([{ "text": "" }]) };
    Value::Array(parts.iter().map(|p| {
        if p.get("type").and_then(|t| t.as_str()) == Some("text") {
            json!({ "text": p.get("text").cloned().unwrap_or_default() })
        } else {
            json!({ "inline_data": {
                "mime_type": p.get("mediaType").cloned().unwrap_or_default(),
                "data": p.get("data").cloned().unwrap_or_default() } })
        }
    }).collect())
}

fn to_openai_content(content: &Value) -> Value {
    if content.is_string() { return content.clone(); }
    let Some(parts) = content.as_array() else { return content.clone() };
    Value::Array(parts.iter().map(|p| {
        if p.get("type").and_then(|t| t.as_str()) == Some("text") {
            json!({ "type": "text", "text": p.get("text").cloned().unwrap_or_default() })
        } else {
            let media = p.get("mediaType").and_then(|m| m.as_str()).unwrap_or("");
            let data = p.get("data").and_then(|d| d.as_str()).unwrap_or("");
            json!({ "type": "image_url",
                    "image_url": { "url": format!("data:{};base64,{}", media, data) } })
        }
    }).collect())
}

fn has_document_part(messages: &[ProxyMessage]) -> bool {
    messages.iter().any(|m| {
        m.content.as_array().is_some_and(|parts| {
            parts.iter().any(|p| p.get("type").and_then(|t| t.as_str()) == Some("document"))
        })
    })
}

// ── HTTP helper ─────────────────────────────────────────────────────────────

/// POST JSON, returning the parsed body. `ureq` turns a non-2xx into an
/// Err(Status) whose body carries the provider's message — surfaced to the
/// caller because it is what makes a bad key or bad model diagnosable.
/// The error text is the PROVIDER's, never our request headers, so no key
/// can ride out in a message.
fn post_json(req: ureq::Request, body: Value, label: &str) -> Result<Value, String> {
    match req.send_json(body) {
        Ok(resp) => resp.into_json::<Value>()
            .map_err(|e| format!("{}: malformed JSON response: {}", label, e)),
        Err(ureq::Error::Status(code, resp)) => {
            let text = resp.into_string().unwrap_or_default();
            Err(format!("{} {}: {}", label, code, text.chars().take(300).collect::<String>()))
        }
        Err(e) => Err(format!("{}: {}", label, e)),
    }
}

fn resolve_key(state: &CredentialsState, provider: &str) -> String {
    // In-memory first (updated the moment the user saves in Settings), then
    // the encrypted DB row — same precedence extraction.rs already uses.
    let (cached, db_field) = match provider {
        "gemini" => (state.gemini_key.lock().ok().map(|g| g.clone()), "gemini_api_key"),
        "openai" => (state.openai_key.lock().ok().map(|g| g.clone()), "openai_api_key"),
        _ => (state.api_key.lock().ok().map(|g| g.clone()), "anthropic_api_key"),
    };
    match cached {
        Some(k) if !k.trim().is_empty() => k,
        _ => load_config_key(db_field).unwrap_or_default(),
    }
}

// ── The command ─────────────────────────────────────────────────────────────

/// Complete a chat turn against the configured provider.
///
/// Credentials are resolved inside this function and never returned. A
/// missing key is an explicit error so the UI can prompt for one, exactly as
/// it did when it checked the key value itself.
///
/// `ureq` is a blocking client and an LLM call can run for a minute, so the
/// request itself is handed to the blocking pool. Only the cheap parts —
/// reading CredentialsState (a Mutex<String>) and the settings rows — happen
/// on the async runtime, because tauri::State cannot cross into
/// spawn_blocking. Without this the whole IPC runtime would stall for the
/// duration of every Describe/Copilot turn.
#[tauri::command]
pub async fn llm_complete(
    state: tauri::State<'_, CredentialsState>,
    provider: String,
    system: String,
    messages: Vec<ProxyMessage>,
    model: Option<String>,
) -> Result<ProxyResponse, String> {
    let provider = provider.trim().to_string();
    // Resolve the credential here (needs `state`), then own it.
    let resolved_key = match provider.as_str() {
        p if p.starts_with("custom:") =>
            load_config_key(&format!("custom_{}_api_key", &p["custom:".len()..])).unwrap_or_default(),
        "gemini" | "openai" => resolve_key(&state, &provider),
        _ => resolve_key(&state, "anthropic"),
    };

    tauri::async_runtime::spawn_blocking(move || {
        llm_complete_blocking(provider, system, messages, model, resolved_key)
    })
    .await
    .map_err(|e| format!("LLM task failed to run: {}", e))?
}

/// The actual provider call. Split out so it can run on the blocking pool
/// with owned data — see llm_complete above.
fn llm_complete_blocking(
    provider: String,
    system: String,
    messages: Vec<ProxyMessage>,
    model: Option<String>,
    resolved_key: String,
) -> Result<ProxyResponse, String> {

    if let Some(preset_id) = provider.strip_prefix("custom:") {
        let base = custom_preset_base_url(preset_id)
            .ok_or_else(|| format!("Unknown provider preset '{}'", preset_id))?;
        if has_document_part(&messages) {
            return Err("PDF attachments aren't supported with this provider. \
                        Switch to Anthropic or Gemini, or attach an image/text file instead.".into());
        }
        let key = resolved_key;
        if key.trim().is_empty() {
            return Err(format!("No API key set for '{}' — add one in Settings.", preset_id));
        }
        let model = model
            .filter(|m| !m.is_empty())
            .or_else(|| load_config_key(&format!("custom_{}_model", preset_id)))
            .unwrap_or_else(|| DEFAULT_OPENAI_MODEL.to_string());

        let body = json!({
            "model": model,
            "messages": openai_messages(&system, &messages),
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        });
        let url = format!("{}/chat/completions", base.trim_end_matches('/'));
        let data = post_openai_shaped(&url, &key, body, preset_id)?;
        return Ok(openai_result(&provider, &model, data));
    }

    match provider.as_str() {
        "gemini" => {
            let key = resolved_key;
            if key.trim().is_empty() {
                return Err("No Gemini API key set — add one in Settings.".into());
            }
            let model = model
                .filter(|m| !m.is_empty())
                .or_else(|| load_config_key("gemini_model_smart"))
                .unwrap_or_else(|| DEFAULT_GEMINI_MODEL.to_string());

            let contents: Vec<Value> = messages.iter().map(|m| json!({
                "role": if m.role == "assistant" { "model" } else { "user" },
                "parts": to_gemini_parts(&m.content),
            })).collect();

            // Key goes in a header, not the query string: a URL with an
            // embedded key ends up in proxy and crash logs.
            let url = format!(
                "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent",
                model
            );
            let data = post_json(
                ureq::post(&url)
                    .set("Content-Type", "application/json")
                    .set("x-goog-api-key", &key),
                json!({
                    "system_instruction": { "parts": [{ "text": system }] },
                    "contents": contents,
                }),
                "Gemini",
            )?;

            let text = data.pointer("/candidates/0/content/parts/0/text")
                .and_then(|t| t.as_str()).unwrap_or("").to_string();
            let tin = data.pointer("/usageMetadata/promptTokenCount")
                .and_then(|v| v.as_i64()).unwrap_or(0);
            let tout = data.pointer("/usageMetadata/candidatesTokenCount")
                .and_then(|v| v.as_i64()).unwrap_or(0);
            Ok(ProxyResponse {
                text,
                usage: ProxyUsage {
                    tokens_in: tin,
                    tokens_out: tout,
                    cost_usd: estimate_cost("gemini", &model, tin, tout),
                    provider,
                    model,
                },
            })
        }

        "openai" => {
            if has_document_part(&messages) {
                return Err("PDF attachments aren't supported with OpenAI. \
                            Switch to Anthropic or Gemini, or attach an image/text file instead.".into());
            }
            let key = resolved_key;
            if key.trim().is_empty() {
                return Err("No OpenAI API key set — add one in Settings.".into());
            }
            let model = model
                .filter(|m| !m.is_empty())
                .or_else(|| load_config_key("openai_model_smart"))
                .unwrap_or_else(|| DEFAULT_OPENAI_MODEL.to_string());

            let body = json!({
                "model": model,
                "messages": openai_messages(&system, &messages),
                "max_completion_tokens": MAX_TOKENS,
                "temperature": 0,
            });
            let data = post_openai_shaped(OPENAI_URL, &key, body, "OpenAI")?;
            Ok(openai_result(&provider, &model, data))
        }

        // Default: Anthropic
        _ => {
            let key = resolved_key;
            if key.trim().is_empty() {
                return Err("No Anthropic API key set — add one in Settings.".into());
            }
            let model = model
                .filter(|m| !m.is_empty())
                .or_else(|| load_config_key("anthropic_model_smart"))
                .unwrap_or_else(|| DEFAULT_ANTHROPIC_MODEL.to_string());

            let msgs: Vec<Value> = messages.iter().map(|m| json!({
                "role": m.role,
                "content": to_anthropic_content(&m.content),
            })).collect();

            // No `anthropic-dangerous-direct-browser-access` header here —
            // this is a server-side call, which is the point of the module.
            let data = post_json(
                ureq::post(ANTHROPIC_URL)
                    .set("Content-Type", "application/json")
                    .set("x-api-key", &key)
                    .set("anthropic-version", "2023-06-01"),
                json!({
                    "model": model,
                    "max_tokens": MAX_TOKENS,
                    "system": system,
                    "messages": msgs,
                }),
                "Claude API",
            )?;

            let text = data.pointer("/content/0/text")
                .and_then(|t| t.as_str()).unwrap_or("").to_string();
            let tin = data.pointer("/usage/input_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
            let tout = data.pointer("/usage/output_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
            Ok(ProxyResponse {
                text,
                usage: ProxyUsage {
                    tokens_in: tin,
                    tokens_out: tout,
                    cost_usd: estimate_cost("anthropic", &model, tin, tout),
                    provider: "anthropic".to_string(),
                    model,
                },
            })
        }
    }
}

fn openai_messages(system: &str, messages: &[ProxyMessage]) -> Vec<Value> {
    let mut out = vec![json!({ "role": "system", "content": system })];
    out.extend(messages.iter().map(|m| json!({
        "role": m.role,
        "content": to_openai_content(&m.content),
    })));
    out
}

/// POST an OpenAI-shaped chat/completions body, retrying once without
/// `temperature` when the model rejects it — gpt-5.x only accepts the
/// default. Mirrors the same fallback in adapters/llm_openai.py and the one
/// llmClient.ts used to do in the renderer.
fn post_openai_shaped(url: &str, key: &str, body: Value, label: &str) -> Result<Value, String> {
    let build = || ureq::post(url)
        .set("Content-Type", "application/json")
        .set("Authorization", &format!("Bearer {}", key));

    match post_json(build(), body.clone(), label) {
        Ok(v) => Ok(v),
        Err(e) if e.contains("temperature") && e.contains("does not support") => {
            let mut retry = body;
            if let Some(obj) = retry.as_object_mut() { obj.remove("temperature"); }
            post_json(build(), retry, label)
        }
        Err(e) => Err(e),
    }
}

fn openai_result(provider: &str, model: &str, data: Value) -> ProxyResponse {
    let text = data.pointer("/choices/0/message/content")
        .and_then(|t| t.as_str()).unwrap_or("").to_string();
    let tin = data.pointer("/usage/prompt_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
    let tout = data.pointer("/usage/completion_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
    ProxyResponse {
        text,
        usage: ProxyUsage {
            tokens_in: tin,
            tokens_out: tout,
            cost_usd: estimate_cost(provider, model, tin, tout),
            provider: provider.to_string(),
            model: model.to_string(),
        },
    }
}

// ── Credential status (replaces the key getters) ────────────────────────────

/// Whether each provider has a usable key — booleans only, never values.
/// This is what the Settings / Ingest / Describe screens now use in place of
/// `get_api_key()` etc., which returned the plaintext secret.
#[tauri::command]
pub fn get_credential_status(state: tauri::State<'_, CredentialsState>) -> Value {
    let set = |p: &str| !resolve_key(&state, p).trim().is_empty();
    let custom: Vec<Value> = load_config_key("custom_providers")
        .and_then(|s| serde_json::from_str::<Vec<String>>(&s).ok())
        .unwrap_or_default()
        .into_iter()
        .map(|id| {
            let has = load_config_key(&format!("custom_{}_api_key", id))
                .is_some_and(|k| !k.trim().is_empty());
            json!({ "id": id, "hasKey": has })
        })
        .collect();

    json!({
        "anthropic": set("anthropic"),
        "gemini":    set("gemini"),
        "openai":    set("openai"),
        "custom":    custom,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn custom_preset_allowlist_rejects_unknown() {
        assert!(custom_preset_base_url("grok").is_some());
        // An arbitrary base URL from the renderer must never be honoured —
        // that would be SSRF with a real API key attached.
        assert!(custom_preset_base_url("http://attacker.example").is_none());
        assert!(custom_preset_base_url("").is_none());
    }

    #[test]
    fn cost_falls_back_per_provider() {
        assert_eq!(cost_per_mtok("anthropic", "claude-sonnet-4-6"), (3.00, 15.00));
        assert_eq!(cost_per_mtok("anthropic", "unknown-model"), (3.00, 15.00));
        assert_eq!(cost_per_mtok("gemini", "gemini-2.5-pro"), (1.25, 10.00));
        assert_eq!(cost_per_mtok("openai", "gpt-4o"), (2.50, 10.00));
    }

    #[test]
    fn document_part_detection() {
        let with_doc = vec![ProxyMessage {
            role: "user".into(),
            content: json!([{ "type": "document", "mediaType": "application/pdf", "data": "x" }]),
        }];
        let plain = vec![ProxyMessage { role: "user".into(), content: json!("hi") }];
        assert!(has_document_part(&with_doc));
        assert!(!has_document_part(&plain));
    }

    #[test]
    fn anthropic_content_passthrough_for_plain_string() {
        assert_eq!(to_anthropic_content(&json!("hello")), json!("hello"));
    }
}

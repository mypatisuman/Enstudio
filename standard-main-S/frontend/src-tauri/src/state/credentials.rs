use std::sync::Mutex;
use crate::config::load_config_key;

// Every credential here is chosen from the frontend Settings screen only —
// no environment-variable fallback. `load_config_key` reads the persisted
// value straight from the `settings` table in studio.db.
pub struct CredentialsState {
    pub(crate) api_key:            Mutex<String>,
    pub(crate) gemini_key:         Mutex<String>,
    pub(crate) openai_key:         Mutex<String>,
}

impl CredentialsState {
    pub fn new() -> Self {
        Self {
            api_key:    Mutex::new(load_config_key("anthropic_api_key").unwrap_or_default()),
            gemini_key: Mutex::new(load_config_key("gemini_api_key").unwrap_or_default()),
            openai_key: Mutex::new(load_config_key("openai_api_key").unwrap_or_default()),
        }
    }
}

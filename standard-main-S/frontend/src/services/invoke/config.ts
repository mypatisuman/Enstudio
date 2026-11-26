// Typed invoke wrappers for src-tauri/src/commands/llm_config.rs.
//
// Note: save_api_key/save_gemini_key/save_models/save_gemini_model/
// save_llm_provider return a loosely-shaped `Value` on the backend (a
// deliberate {ok:true}/{ok:false,error} union) rather than a typed DTO, so
// their wrappers stay untyped (`unknown`) too instead of inventing a
// frontend-only shape that could drift from reality.

import { invoke } from '@tauri-apps/api/core'

export function getApiKeyStatus(): Promise<unknown> {
  return invoke('get_api_key_status')
}

// Per-provider "is a key configured?" — booleans only. Replaces the four
// getters that returned the plaintext secret to the webview (Phase 0). The
// values themselves now stay in the Rust process; see
// src-tauri/src/commands/llm_proxy.rs.
export interface CredentialStatus {
  anthropic: boolean
  gemini: boolean
  openai: boolean
  custom: { id: string; hasKey: boolean }[]
}

export function getCredentialStatus(): Promise<CredentialStatus> {
  return invoke('get_credential_status')
}

export function saveApiKey(key: string): Promise<unknown> {
  return invoke('save_api_key', { key })
}

export function getModels(): Promise<{ anthropic: string }> {
  return invoke('get_models')
}

export function saveModels(anthropic: string): Promise<unknown> {
  return invoke('save_models', { anthropic })
}

export function saveGeminiKey(key: string): Promise<unknown> {
  return invoke('save_gemini_key', { key })
}

export function getGeminiModel(): Promise<{ gemini: string }> {
  return invoke('get_gemini_model')
}

export function saveGeminiModel(model: string): Promise<unknown> {
  return invoke('save_gemini_model', { model })
}

export function saveOpenaiKey(key: string): Promise<unknown> {
  return invoke('save_openai_key', { key })
}

export function getOpenaiModel(): Promise<{ openai: string }> {
  return invoke('get_openai_model')
}

export function saveOpenaiModel(model: string): Promise<unknown> {
  return invoke('save_openai_model', { model })
}

export function getLlmProvider(): Promise<string> {
  return invoke('get_llm_provider')
}

export function saveLlmProvider(provider: string): Promise<unknown> {
  return invoke('save_llm_provider', { provider })
}

// ── Custom (named-preset) providers — Grok, DeepSeek, Mistral, Groq,
// OpenRouter, Together... added via the "+" button in Settings. ────────────

export interface CustomProviderRow {
  id: string
  model: string
  hasKey: boolean
}

export function getCustomProviders(): Promise<CustomProviderRow[]> {
  return invoke('get_custom_providers')
}

export function saveCustomProvider(id: string, apiKey: string, model: string): Promise<unknown> {
  return invoke('save_custom_provider', { id, apiKey, model })
}

export function removeCustomProvider(id: string): Promise<unknown> {
  return invoke('remove_custom_provider', { id })
}

// No getCustomProviderKey: use getCredentialStatus().custom to learn whether
// a preset has a key, and llm_complete to actually use it.

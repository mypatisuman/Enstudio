// LLM client — thin wrapper over the Rust proxy (src-tauri/src/commands/llm_proxy.rs).
//
// Phase 0: this file used to hold provider API keys in renderer memory and
// fetch() api.anthropic.com / api.openai.com / generativelanguage directly.
// Any script-injection bug in the webview could read those keys. Provider
// routing, request shaping, and the cost tables now all live in Rust; the
// key never crosses the IPC boundary.
//
// The exported signature is deliberately unchanged so DescribeScreen and the
// Copilot's llmStream both keep working without touching their call sites —
// there is still exactly ONE LLM client on the frontend.

import { invoke } from '@tauri-apps/api/core'
import type { LlmProvider } from '../../../domain/llm/credentials'
import { SYSTEM_PROMPT } from '../constants'

// Kept for source compatibility with existing call sites. The key fields are
// no longer read by anything: the Rust proxy resolves credentials itself
// from the DPAPI-encrypted `settings` table. Only `provider` and the model
// overrides still carry meaning.
export interface LlmCredentials {
  provider: LlmProvider
  anthropicModel?: string
  geminiModel?: string
  openaiModel?: string
  customModel?: string
}

export type ApiContentPart =
  | { type: 'text'; text: string }
  | { type: 'image'; mediaType: string; data: string }      // base64, no data: prefix
  | { type: 'document'; mediaType: string; data: string }   // PDF, base64

export interface ApiMessage { role: string; content: string | ApiContentPart[] }

export interface LlmUsage {
  tokensIn: number
  tokensOut: number
  provider: string
  model: string
  costUsd: number
}

/** Model override for the active provider, or undefined to let Rust pick. */
function modelFor(creds: LlmCredentials): string | undefined {
  if (creds.provider === 'gemini') return creds.geminiModel
  if (creds.provider === 'openai') return creds.openaiModel
  if (creds.provider.startsWith('custom:')) return creds.customModel
  return creds.anthropicModel
}

export async function callLlm(
  apiMessages: ApiMessage[],
  creds: LlmCredentials,
  // Optional override so other features (e.g. the Copilot) can reuse this
  // exact provider routing with their own system prompt.
  system: string = SYSTEM_PROMPT,
): Promise<{ text: string, usage: LlmUsage }> {
  // invoke rejects with the Rust Err(String) — a provider error, a missing
  // key, or an unsupported attachment all arrive as a plain message, the
  // same shapes the old inline fetch threw.
  return invoke<{ text: string, usage: LlmUsage }>('llm_complete', {
    provider: creds.provider,
    system,
    messages: apiMessages,
    model: modelFor(creds),
  })
}

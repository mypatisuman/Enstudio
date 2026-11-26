import { callLlm, type LlmCredentials } from '../../describe/utils/llmClient'

export interface StreamUsage { tokensIn: number, tokensOut: number, provider: string, model: string, costUsd: number }

// Emits an assistant reply through onToken.
//
// Phase 0: the Anthropic branch used to open its own SSE fetch to
// api.anthropic.com with `creds.apiKey` and the
// `anthropic-dangerous-direct-browser-access` header — a second copy of the
// credential in renderer memory, and a second exfiltration path. It now
// takes the same route the other three providers already took: one
// callLlm() through the Rust proxy, emitted in a single chunk.
//
// ponytail: token-by-token streaming is gone, not broken — the reply still
// arrives in full and the usage numbers are unchanged. Restore it by
// streaming inside src-tauri/src/commands/llm_proxy.rs and emitting Tauri
// events (the pattern extraction.rs already uses for NDJSON progress), not
// by moving the key back into the webview.
export async function streamLlm(
  system: string,
  apiMessages: { role: string; content: string }[],
  creds: LlmCredentials,
  onToken: (chunk: string) => void,
): Promise<{ content: string, usage: StreamUsage }> {
  const { text, usage } = await callLlm(apiMessages, creds, system)
  onToken(text)
  return { content: text, usage }
}

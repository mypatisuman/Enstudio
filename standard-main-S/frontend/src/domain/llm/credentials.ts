// LLM provider/credential business rules — shared by Ingest, Describe, and
// Usage screens. Only the genuinely identical checks are consolidated here;
// see the notes below for two cases that were deliberately NOT merged
// because they differ in a real (if small) way.

// `custom:<presetId>` covers any added named preset (Grok, DeepSeek, Mistral,
// Groq, OpenRouter, Together...) — see domain/llm/customProviderPresets.ts.
export type LlmProvider = 'anthropic' | 'gemini' | 'openai' | `custom:${string}`

// Identical in IngestScreen and DescribeScreen before this extraction —
// validates a string received from get_llm_provider() narrows to LlmProvider.
export function isValidProvider(p: string): p is LlmProvider {
  return p === 'anthropic' || p === 'gemini' || p === 'openai' || p.startsWith('custom:')
}

// isNonEmpty was removed in Phase 0. Its only job was testing a fetched API
// key for emptiness in IngestScreen/UsageScreen — and the renderer no longer
// fetches keys at all. hasCredential() below answers the same question from
// the backend's booleans.

// Phase 0: this used to take the credential VALUES, because the screens held
// them. They no longer do — the backend answers "is a key configured?" with
// booleans and never hands over the secret. Same decision, no secret needed.
export interface ProviderCredentialState {
  anthropic: boolean
  gemini: boolean
  openai: boolean
  custom: { id: string; hasKey: boolean }[]
}

export function hasCredential(
  provider: LlmProvider,
  status: ProviderCredentialState | null | undefined,
): boolean {
  if (!status) return false
  if (provider === 'gemini') return status.gemini
  if (provider === 'openai') return status.openai
  if (provider.startsWith('custom:')) {
    const id = provider.slice('custom:'.length)
    return status.custom.some(c => c.id === id && c.hasKey)
  }
  return status.anthropic
}

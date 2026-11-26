// Named presets for third-party OpenAI-compatible LLM providers — mirrors
// studio/adapters/llm_presets.py so the frontend (Describe's direct fetch)
// and the Python extraction pipeline agree on the same base URLs/defaults.

export interface CustomProviderPreset {
  label: string
  baseUrl: string
  defaultModel: string
  keyPlaceholder: string
}

export const CUSTOM_PROVIDER_PRESETS: Record<string, CustomProviderPreset> = {
  grok: {
    label: 'Grok (xAI)',
    baseUrl: 'https://api.x.ai/v1',
    defaultModel: 'grok-4',
    keyPlaceholder: 'xai-...',
  },
  deepseek: {
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
    defaultModel: 'deepseek-chat',
    keyPlaceholder: 'sk-...',
  },
  mistral: {
    label: 'Mistral AI',
    baseUrl: 'https://api.mistral.ai/v1',
    defaultModel: 'mistral-large-latest',
    keyPlaceholder: '...',
  },
  groq: {
    label: 'Groq',
    baseUrl: 'https://api.groq.com/openai/v1',
    defaultModel: 'llama-3.3-70b-versatile',
    keyPlaceholder: 'gsk_...',
  },
  openrouter: {
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    defaultModel: 'openai/gpt-4o',
    keyPlaceholder: 'sk-or-...',
  },
  together: {
    label: 'Together AI',
    baseUrl: 'https://api.together.xyz/v1',
    defaultModel: 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
    keyPlaceholder: '...',
  },
}

export function customProviderLabel(provider: string): string {
  const id = provider.startsWith('custom:') ? provider.slice('custom:'.length) : provider
  return CUSTOM_PROVIDER_PRESETS[id]?.label ?? id
}

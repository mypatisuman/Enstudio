import { useState } from 'react'
import type { LlmProvider } from '../../../domain/llm/credentials'
import { CUSTOM_PROVIDER_PRESETS, customProviderLabel } from '../../../domain/llm/customProviderPresets'

export function ApiKeyModal({
  provider, onConfirm, onClose,
}: { provider: LlmProvider; onConfirm: (key: string) => void; onClose: () => void }) {
  const [val, setVal] = useState('')
  const isCustom = provider.startsWith('custom:')
  const label       = provider === 'gemini' ? 'Google Gemini' : provider === 'openai' ? 'OpenAI'
    : isCustom ? customProviderLabel(provider) : 'Anthropic'
  const placeholder = provider === 'gemini' ? 'AIza…' : provider === 'openai' ? 'sk-…'
    : isCustom ? (CUSTOM_PROVIDER_PRESETS[provider.slice('custom:'.length)]?.keyPlaceholder ?? '...') : 'sk-ant-…'
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
    }} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '28px 28px 24px', width: 400,
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--text-primary)' }}>
          ✦ {label} API Key
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Required for Describe mode. Saved to the settings table in studio.db.
        </div>
        <input
          type="password" placeholder={placeholder} value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && val.trim()) onConfirm(val.trim()) }}
          autoFocus
          style={{
            background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
            borderRadius: 6, color: 'var(--text-primary)', font: 'inherit',
            fontSize: 13, padding: '9px 12px', outline: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!val.trim()}
            onClick={() => onConfirm(val.trim())}>
            Save &amp; Use
          </button>
        </div>
      </div>
    </div>
  )
}

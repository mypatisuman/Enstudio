import { TextInput } from '../../../shared/components/input/TextInput'
import { CUSTOM_PROVIDER_PRESETS, customProviderLabel } from '../../../domain/llm/customProviderPresets'

export function IngestApiKeyModal({
  activeProvider, apiKeyInput, setApiKeyInput,
  pendingId, onConfirm, onClose, onCancel,
}: {
  activeProvider: 'anthropic' | 'gemini' | 'openai' | `custom:${string}`
  apiKeyInput: string
  setApiKeyInput: (v: string) => void
  pendingId: number | null
  onConfirm: () => void
  onClose: () => void
  onCancel: () => void
}) {
  const isCustom = activeProvider.startsWith('custom:')
  const label = activeProvider === 'gemini' ? 'Google Gemini' : activeProvider === 'openai' ? 'OpenAI'
    : isCustom ? customProviderLabel(activeProvider) : 'Anthropic'
  const placeholder = activeProvider === 'gemini' ? 'AIza…' : activeProvider === 'openai' ? 'sk-…'
    : isCustom ? (CUSTOM_PROVIDER_PRESETS[activeProvider.slice('custom:'.length)]?.keyPlaceholder ?? '...') : 'sk-ant-…'
  return (
    <div style={{
      position: 'fixed', inset: 0,
      background: 'rgba(4,8,20,0.78)',
      backdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 9999, animation: 'fade-up 0.18s ease',
    }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--accent-border)',
        borderRadius: 16,
        padding: '28px 28px 24px',
        width: 430,
        display: 'flex', flexDirection: 'column', gap: 14,
        boxShadow: '0 24px 64px rgba(0,0,0,0.7), 0 0 0 1px rgba(77,142,248,0.1)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8,
            background: 'var(--accent-dim)', border: '1px solid var(--accent-border)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          </div>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
            {label} API Key
          </div>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.65, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 14 }}>
          Required for {label} extraction. Saved to the settings table in studio.db.
        </div>
        <TextInput
          type="password"
          placeholder={placeholder}
          value={apiKeyInput}
          onChange={e => setApiKeyInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') onConfirm() }}
          autoFocus
        />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={!apiKeyInput.trim()} onClick={onConfirm}>
            {pendingId !== null ? 'Save & Extract' : 'Save Key'}
          </button>
        </div>
      </div>
    </div>
  )
}

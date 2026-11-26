import { useState, useRef, useEffect, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Key, Save, Plus, X, ChevronDown } from 'lucide-react'
import { PasswordInput } from '../../../shared/components/input/PasswordInput'
import { CUSTOM_PROVIDER_PRESETS } from '../../../domain/llm/customProviderPresets'
import type { CustomProviderRow } from '../../../services/invoke/config'

type Provider = 'anthropic' | 'gemini' | 'openai' | `custom:${string}`

const BUILTIN_PROVIDERS: { id: Provider; label: string }[] = [
  { id: 'anthropic', label: 'Claude' },
  { id: 'gemini',    label: 'Gemini' },
  { id: 'openai',    label: 'OpenAI' },
]

const fieldStyle: CSSProperties = {
  background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '10px 14px', color: 'var(--text-primary)', outline: 'none',
}

export function ApiKeysSection({
  activeProvider, onSwitchProvider,
  anthropicKey, setAnthropicKey, anthropicModel, setAnthropicModel,
  geminiKey, setGeminiKey, geminiModel, setGeminiModel,
  openaiKey, setOpenaiKey, openaiModel, setOpenaiModel,
  showAnthropic, setShowAnthropic, showGemini, setShowGemini,
  showOpenai, setShowOpenai,
  onSaveAnthropic, onSaveGemini, onSaveOpenai,
  customProviders, customKeys, setCustomKey, customModels, setCustomModel,
  customShow, setCustomShow,
  onAddCustomProvider, onSaveCustomProvider, onRemoveCustomProvider,
  keySet,
}: {
  // Phase 0: key fields start empty because the backend no longer returns a
  // stored credential to the webview. `keySet` says whether one exists so
  // the placeholder can distinguish "configured, leave blank to keep" from
  // "not configured yet".
  keySet?: { anthropic: boolean; gemini: boolean; openai: boolean }
  activeProvider: Provider
  onSwitchProvider: (p: Provider) => void
  anthropicKey: string
  setAnthropicKey: (v: string) => void
  anthropicModel: string
  setAnthropicModel: (v: string) => void
  geminiKey: string
  setGeminiKey: (v: string) => void
  geminiModel: string
  setGeminiModel: (v: string) => void
  openaiKey: string
  setOpenaiKey: (v: string) => void
  openaiModel: string
  setOpenaiModel: (v: string) => void
  showAnthropic: boolean
  setShowAnthropic: (v: boolean) => void
  showGemini: boolean
  setShowGemini: (v: boolean) => void
  showOpenai: boolean
  setShowOpenai: (v: boolean) => void
  onSaveAnthropic: () => void
  onSaveGemini: () => void
  onSaveOpenai: () => void
  customProviders: CustomProviderRow[]
  customKeys: Record<string, string>
  setCustomKey: (id: string, v: string) => void
  customModels: Record<string, string>
  setCustomModel: (id: string, v: string) => void
  customShow: Record<string, boolean>
  setCustomShow: (id: string, v: boolean) => void
  onAddCustomProvider: (presetId: string, apiKey: string, model: string) => void
  onSaveCustomProvider: (presetId: string) => void
  onRemoveCustomProvider: (presetId: string) => void
}) {
  const addedIds = new Set(customProviders.map(p => p.id))
  const availablePresets = Object.entries(CUSTOM_PROVIDER_PRESETS).filter(([id]) => !addedIds.has(id))

  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const [addFormPresetId, setAddFormPresetId] = useState('')
  const [addFormKey, setAddFormKey] = useState('')
  const [addFormModel, setAddFormModel] = useState('')
  const [addFormShowKey, setAddFormShowKey] = useState(false)
  const [addProviderPickerOpen, setAddProviderPickerOpen] = useState(false)

  function closeAddForm() {
    setAddMenuOpen(false)
    setAddProviderPickerOpen(false)
    setAddFormPresetId('')
    setAddFormKey('')
    setAddFormModel('')
    setAddFormShowKey(false)
  }

  function submitAddForm() {
    if (!addFormPresetId) return
    onAddCustomProvider(addFormPresetId, addFormKey, addFormModel)
    closeAddForm()
  }

  const allProviders: { id: Provider; label: string }[] = [
    ...BUILTIN_PROVIDERS,
    ...customProviders.map(({ id }) => ({
      id: `custom:${id}` as Provider,
      label: CUSTOM_PROVIDER_PRESETS[id]?.label ?? id,
    })),
  ]
  const activeLabel = allProviders.find(p => p.id === activeProvider)?.label ?? activeProvider

  const [activeMenuOpen, setActiveMenuOpen] = useState(false)
  const activeMenuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!activeMenuOpen) return
    const onDown = (e: MouseEvent) => {
      if (!activeMenuRef.current?.contains(e.target as Node)) setActiveMenuOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [activeMenuOpen])

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 10, margin: 0, fontSize: 20, color: 'var(--text-primary)' }}>
        <Key size={20} className="text-accent" /> API Keys
      </h2>

      {/* Active provider — the ONE place this is chosen. Extraction, Describe,
          and everything else just read this; they no longer have their own
          switcher, so there's a single source of truth for "which engine runs". */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, position: 'relative' }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Active provider</span>

        <div ref={activeMenuRef} style={{ position: 'relative' }}>
          <button
            type="button"
            className={`fsel${activeMenuOpen ? ' fsel--open' : ''}`}
            onClick={() => setActiveMenuOpen(v => !v)}
            style={{ width: 170, padding: '6px 10px' }}
          >
            <span className="fsel-value">{activeLabel}</span>
            <ChevronDown size={15} className="fsel-chevron" />
          </button>

          {activeMenuOpen && (
            <div className="fsel-menu" style={{ position: 'absolute', top: '100%', left: 0, marginTop: 6, width: 170 }}>
              {allProviders.map(({ id: p, label }) => (
                <button
                  key={p}
                  type="button"
                  className={`fsel-opt${activeProvider === p ? ' fsel-opt--sel' : ''}`}
                  onClick={() => { onSwitchProvider(p); setActiveMenuOpen(false) }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setAddMenuOpen(true)}
          disabled={availablePresets.length === 0}
          style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 14px 5px 10px', borderRadius: 20, fontSize: 12, marginLeft: 'auto' }}
        >
          <Plus size={13} /> Add
        </button>
      </div>

      {addMenuOpen && createPortal(
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(4,8,20,0.78)', backdropFilter: 'blur(6px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10000,
          }}
          onClick={e => { if (e.target === e.currentTarget) closeAddForm() }}
        >
          <div style={{
            background: 'var(--bg-secondary)', border: '1px solid var(--accent-border)', borderRadius: 16,
            padding: '28px 28px 24px', width: 400, display: 'flex', flexDirection: 'column', gap: 14,
            boxShadow: '0 24px 64px rgba(0,0,0,0.7), 0 0 0 1px rgba(77,142,248,0.1)',
          }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--text-primary)' }}>Add Provider</div>

            {/* Step 1 — choose the provider */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Provider</span>
              <div style={{ position: 'relative' }}>
                <button
                  type="button"
                  className={`fsel${addProviderPickerOpen ? ' fsel--open' : ''}`}
                  onClick={() => setAddProviderPickerOpen(v => !v)}
                  style={{ width: '100%' }}
                >
                  <span className="fsel-value">
                    {addFormPresetId ? CUSTOM_PROVIDER_PRESETS[addFormPresetId]?.label : 'Choose provider'}
                  </span>
                  <ChevronDown size={15} className="fsel-chevron" />
                </button>
                {addProviderPickerOpen && (
                  <div className="fsel-menu" style={{ position: 'absolute', top: '100%', left: 0, marginTop: 4, width: '100%' }}>
                    {availablePresets.map(([id, preset]) => (
                      <button
                        key={id}
                        type="button"
                        className={`fsel-opt${addFormPresetId === id ? ' fsel-opt--sel' : ''}`}
                        onClick={() => {
                          setAddFormPresetId(id)
                          setAddProviderPickerOpen(false)
                        }}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Step 2 — key + model, only once a provider's picked */}
            {addFormPresetId && (
              <>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>API Key</span>
                  <PasswordInput
                    value={addFormKey} onChange={setAddFormKey}
                    placeholder={CUSTOM_PROVIDER_PRESETS[addFormPresetId]?.keyPlaceholder ?? '...'}
                    visible={addFormShowKey} onToggleVisible={() => setAddFormShowKey(!addFormShowKey)}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Model</span>
                  <input
                    type="text"
                    value={addFormModel}
                    onChange={e => setAddFormModel(e.target.value)}
                    placeholder={CUSTOM_PROVIDER_PRESETS[addFormPresetId]?.defaultModel ?? 'model'}
                    style={fieldStyle}
                    onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                    onBlur={e => e.target.style.borderColor = 'var(--border)'}
                  />
                </div>
              </>
            )}

            {/* Step 3 — add */}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-ghost" onClick={closeAddForm}>Cancel</button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!addFormPresetId}
                onClick={submitAddForm}
                style={{ display: 'flex', alignItems: 'center', gap: 8 }}
              >
                <Plus size={14} /> Add
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12, padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>

        {/* Anthropic */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
            Anthropic (Claude) {activeProvider === 'anthropic' && <span style={{ color: 'var(--accent)', fontWeight: 700 }}>· active</span>}
          </label>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>API Key</span>
              <PasswordInput
                value={anthropicKey} onChange={setAnthropicKey}
                placeholder={keySet?.anthropic ? 'configured — leave blank to keep' : 'sk-ant-...'}
                visible={showAnthropic} onToggleVisible={() => setShowAnthropic(!showAnthropic)}
              />
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Extraction model</span>
              <input
                type="text"
                value={anthropicModel}
                onChange={e => setAnthropicModel(e.target.value)}
                placeholder="claude-sonnet-4-6"
                style={fieldStyle}
                onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button className="btn btn-primary" onClick={onSaveAnthropic} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Save size={14} /> Save
              </button>
            </div>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)' }} />

        {/* Gemini */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
            Google Gemini {activeProvider === 'gemini' && <span style={{ color: 'var(--accent)', fontWeight: 700 }}>· active</span>}
          </label>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>API Key</span>
              <PasswordInput
                value={geminiKey} onChange={setGeminiKey}
                placeholder={keySet?.gemini ? 'configured — leave blank to keep' : 'AIza...'}
                visible={showGemini} onToggleVisible={() => setShowGemini(!showGemini)}
              />
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Extraction model</span>
              <input
                type="text"
                value={geminiModel}
                onChange={e => setGeminiModel(e.target.value)}
                placeholder="gemini-2.5-flash"
                style={fieldStyle}
                onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button className="btn btn-primary" onClick={onSaveGemini} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Save size={14} /> Save
              </button>
            </div>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)' }} />

        {/* OpenAI (public API) — just a key + model, same shape as Anthropic/Gemini.
            One fixed shared endpoint (api.openai.com), so there's nothing else to ask. */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
            OpenAI {activeProvider === 'openai' && <span style={{ color: 'var(--accent)', fontWeight: 700 }}>· active</span>}
          </label>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>API Key</span>
              <PasswordInput
                value={openaiKey} onChange={setOpenaiKey}
                placeholder={keySet?.openai ? 'configured — leave blank to keep' : 'sk-...'}
                visible={showOpenai} onToggleVisible={() => setShowOpenai(!showOpenai)}
              />
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Model</span>
              <input
                type="text"
                value={openaiModel}
                onChange={e => setOpenaiModel(e.target.value)}
                placeholder="gpt-5.5"
                style={fieldStyle}
                onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button className="btn btn-primary" onClick={onSaveOpenai} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Save size={14} /> Save
              </button>
            </div>
          </div>
        </div>

        {/* Custom (named-preset) providers — added via the "+" button above.
            Same key + model shape as OpenAI; each just points at a different
            base URL (see domain/llm/customProviderPresets.ts). */}
        {customProviders.map(({ id }) => {
          const preset = CUSTOM_PROVIDER_PRESETS[id]
          const providerKey = `custom:${id}` as const
          return (
            <div key={id}>
              <div style={{ borderTop: '1px solid var(--border)', marginBottom: 20 }} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
                    {preset?.label ?? id} {activeProvider === providerKey && <span style={{ color: 'var(--accent)', fontWeight: 700 }}>· active</span>}
                  </label>
                  <button
                    onClick={() => onRemoveCustomProvider(id)}
                    title="Remove provider"
                    style={{
                      width: 20, height: 20, borderRadius: '50%', display: 'flex',
                      alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
                      border: 'none', background: 'transparent', color: 'var(--text-dim)',
                    }}
                  >
                    <X size={13} />
                  </button>
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>API Key</span>
                    <PasswordInput
                      value={customKeys[id] ?? ''} onChange={v => setCustomKey(id, v)}
                      placeholder={preset?.keyPlaceholder ?? '...'}
                      visible={!!customShow[id]} onToggleVisible={() => setCustomShow(id, !customShow[id])}
                    />
                  </div>
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Model</span>
                    <input
                      type="text"
                      value={customModels[id] ?? ''}
                      onChange={e => setCustomModel(id, e.target.value)}
                      placeholder={preset?.defaultModel ?? 'model'}
                      style={fieldStyle}
                      onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                      onBlur={e => e.target.style.borderColor = 'var(--border)'}
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                    <button className="btn btn-primary" onClick={() => onSaveCustomProvider(id)} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Save size={14} /> Save
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )
        })}

      </div>
    </section>
  )
}

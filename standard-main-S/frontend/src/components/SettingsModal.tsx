import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { toast } from 'sonner'
import { X } from 'lucide-react'
import * as usageService from '../services/usage'
import type { CustomProviderRow } from '../services/invoke/config'
import { CUSTOM_PROVIDER_PRESETS } from '../domain/llm/customProviderPresets'
import { ApiKeysSection } from '../features/usage/components/ApiKeysSection'

/** Real settings — AI provider API keys & models (same store as UsageScreen). */
export function SettingsModal({ onClose }: {
  onClose: () => void
}) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const dismiss = () => { setOpen(false); setTimeout(onClose, 160) }

  const [anthropicKey, setAnthropicKey] = useState('')
  const [anthropicModel, setAnthropicModel] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [geminiModel, setGeminiModel] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [openaiModel, setOpenaiModel] = useState('')
  const [showAnthropic, setShowAnthropic] = useState(false)
  const [showGemini, setShowGemini] = useState(false)
  const [showOpenai, setShowOpenai] = useState(false)
  // Which provider extraction/Describe/etc. actually use — the single source
  // of truth for this now lives here (Settings), not duplicated as its own
  // switcher on the Upload screen, so there's one place to change it.
  const [activeProvider, setActiveProvider] = useState<'anthropic' | 'gemini' | 'openai' | `custom:${string}`>('anthropic')

  // Custom (named-preset) providers — added via the "+" button. Each row's
  // key/model/show-password state is keyed by preset id (e.g. 'grok').
  const [customProviders, setCustomProviders] = useState<CustomProviderRow[]>([])
  const [customKeys,   setCustomKeys]   = useState<Record<string, string>>({})
  const [customModels, setCustomModels] = useState<Record<string, string>>({})
  const [customShow,   setCustomShow]   = useState<Record<string, boolean>>({})

  // Phase 0: key inputs are no longer pre-filled with the stored secret —
  // the backend will not hand a credential to the webview. We load a
  // per-provider boolean instead and show "configured" in the placeholder;
  // an empty field on save means "leave the existing key alone".
  const [keySet, setKeySet] = useState<{ anthropic: boolean; gemini: boolean; openai: boolean }>(
    { anthropic: false, gemini: false, openai: false })

  useEffect(() => {
    (async () => {
      try {
        const status = await usageService.getCredentialStatus()
        setKeySet({ anthropic: status.anthropic, gemini: status.gemini, openai: status.openai })
        setAnthropicModel((await usageService.getModels()).anthropic)
        setGeminiModel((await usageService.getGeminiModel()).gemini)
        setOpenaiModel((await usageService.getOpenaiModel()).openai)
        const provider = await usageService.getLlmProvider()
        if (provider === 'anthropic' || provider === 'gemini' || provider === 'openai' || provider.startsWith('custom:')) {
          setActiveProvider(provider as 'anthropic' | 'gemini' | 'openai' | `custom:${string}`)
        }

        const rows = await usageService.getCustomProviders()
        setCustomProviders(rows)
        const models: Record<string, string> = {}
        for (const row of rows) models[row.id] = row.model
        setCustomModels(models)
        // Custom keys stay blank for the same reason; row.hasKey drives the UI.
        setCustomKeys({})
      } catch (e) {
        console.error('Failed to load settings', e)
      }
    })()
  }, [])

  async function handleSwitchProvider(p: 'anthropic' | 'gemini' | 'openai' | `custom:${string}`) {
    setActiveProvider(p)
    try {
      await usageService.saveLlmProvider(p)
      const label = p === 'anthropic' ? 'Claude' : p === 'gemini' ? 'Gemini' : p === 'openai' ? 'OpenAI'
        : CUSTOM_PROVIDER_PRESETS[p.slice('custom:'.length)]?.label ?? p
      toast.success(`Active provider: ${label}`)
    } catch {
      toast.error('Failed to switch provider')
    }
  }

  // An empty key field means "keep what's stored" — the field starts empty
  // now that we never read the secret back, so saving a model change alone
  // must not wipe the key.
  async function handleSaveAnthropic() {
    try {
      const k = anthropicKey.trim()
      if (k) { await usageService.saveApiKey(k); setKeySet(s => ({ ...s, anthropic: true })); setAnthropicKey('') }
      await usageService.saveModels(anthropicModel.trim())
      toast.success('Anthropic settings saved')
    } catch {
      toast.error('Failed to save Anthropic settings')
    }
  }

  async function handleSaveGemini() {
    try {
      const k = geminiKey.trim()
      if (k) { await usageService.saveGeminiKey(k); setKeySet(s => ({ ...s, gemini: true })); setGeminiKey('') }
      await usageService.saveGeminiModel(geminiModel.trim())
      toast.success('Gemini settings saved')
    } catch {
      toast.error('Failed to save Gemini settings')
    }
  }

  async function handleSaveOpenai() {
    try {
      const k = openaiKey.trim()
      if (k) { await usageService.saveOpenaiKey(k); setKeySet(s => ({ ...s, openai: true })); setOpenaiKey('') }
      await usageService.saveOpenaiModel(openaiModel.trim())
      toast.success('OpenAI settings saved')
    } catch {
      toast.error('Failed to save OpenAI settings')
    }
  }

  async function handleAddCustomProvider(presetId: string, apiKey: string, model: string) {
    if (customProviders.some(p => p.id === presetId)) return
    const trimmedKey   = apiKey.trim()
    const trimmedModel = model.trim() || CUSTOM_PROVIDER_PRESETS[presetId]?.defaultModel || ''
    setCustomProviders(prev => [...prev, { id: presetId, model: trimmedModel, hasKey: !!trimmedKey }])
    setCustomModels(prev => ({ ...prev, [presetId]: trimmedModel }))
    setCustomKeys(prev => ({ ...prev, [presetId]: trimmedKey }))
    try {
      await usageService.saveCustomProvider(presetId, trimmedKey, trimmedModel)
      toast.success(`${CUSTOM_PROVIDER_PRESETS[presetId]?.label ?? presetId} added`)
    } catch {
      toast.error('Failed to add provider')
    }
  }

  async function handleSaveCustomProvider(presetId: string) {
    try {
      const apiKey = (customKeys[presetId] ?? '').trim()
      const model  = (customModels[presetId] ?? '').trim()
      await usageService.saveCustomProvider(presetId, apiKey, model)
      toast.success(`${CUSTOM_PROVIDER_PRESETS[presetId]?.label ?? presetId} settings saved`)
    } catch {
      toast.error('Failed to save provider settings')
    }
  }

  async function handleRemoveCustomProvider(presetId: string) {
    try {
      await usageService.removeCustomProvider(presetId)
      setCustomProviders(prev => prev.filter(p => p.id !== presetId))
      setCustomModels(prev => { const n = { ...prev }; delete n[presetId]; return n })
      setCustomKeys(prev => { const n = { ...prev }; delete n[presetId]; return n })
      // Switching away from a provider that's just been removed avoids
      // leaving "active" pointed at a preset with nothing configured.
      if (activeProvider === `custom:${presetId}`) {
        setActiveProvider('anthropic')
        await usageService.saveLlmProvider('anthropic')
      }
      toast.success(`${CUSTOM_PROVIDER_PRESETS[presetId]?.label ?? presetId} removed`)
    } catch {
      toast.error('Failed to remove provider')
    }
  }

  return createPortal(
    <div
      className={`modal-backdrop${open ? ' open' : ''}`}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
      }}
      onClick={e => { if (e.target === e.currentTarget) dismiss() }}
    >
      <div className="modal-dialog" style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '22px 22px 18px', width: 560, maxHeight: '86vh',
        display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>Settings</div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        <div className="settings-scroll">
          <ApiKeysSection
            keySet={keySet}
            activeProvider={activeProvider} onSwitchProvider={handleSwitchProvider}
            anthropicKey={anthropicKey} setAnthropicKey={setAnthropicKey}
            anthropicModel={anthropicModel} setAnthropicModel={setAnthropicModel}
            geminiKey={geminiKey} setGeminiKey={setGeminiKey}
            geminiModel={geminiModel} setGeminiModel={setGeminiModel}
            openaiKey={openaiKey} setOpenaiKey={setOpenaiKey}
            openaiModel={openaiModel} setOpenaiModel={setOpenaiModel}
            showAnthropic={showAnthropic} setShowAnthropic={setShowAnthropic}
            showGemini={showGemini} setShowGemini={setShowGemini}
            showOpenai={showOpenai} setShowOpenai={setShowOpenai}
            onSaveAnthropic={handleSaveAnthropic}
            onSaveGemini={handleSaveGemini}
            onSaveOpenai={handleSaveOpenai}
            customProviders={customProviders}
            customKeys={customKeys}
            setCustomKey={(id, v) => setCustomKeys(prev => ({ ...prev, [id]: v }))}
            customModels={customModels}
            setCustomModel={(id, v) => setCustomModels(prev => ({ ...prev, [id]: v }))}
            customShow={customShow}
            setCustomShow={(id, v) => setCustomShow(prev => ({ ...prev, [id]: v }))}
            onAddCustomProvider={handleAddCustomProvider}
            onSaveCustomProvider={handleSaveCustomProvider}
            onRemoveCustomProvider={handleRemoveCustomProvider}
          />
        </div>
      </div>
    </div>,
    document.body,
  )
}

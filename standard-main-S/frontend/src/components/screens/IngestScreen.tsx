import { useState, useEffect, useCallback, useRef } from 'react'
import { emit }  from '@tauri-apps/api/event'
import type { Project, Screen } from '../../App'
import { useExtraction } from '../../state/useExtraction'
import * as ingestService from '../../services/ingest'
import * as llmConfigService from '../../services/llmConfig'
import { isValidProvider, hasCredential } from '../../domain/llm/credentials'
import { NoProjectState } from '../../shared/components/empty/NoProjectState'
import type { Source } from '../../features/ingest/types'
import { openFileDialog } from '../../features/ingest/utils'
import { ExtractionProgressPanel } from '../../features/ingest/components/ExtractionProgressPanel'
import { UploadZone } from '../../features/ingest/components/UploadZone'
import { SourceList } from '../../features/ingest/components/SourceList'
import { IngestApiKeyModal } from '../../features/ingest/components/IngestApiKeyModal'
import { SettingsModal } from '../SettingsModal'

interface Props {
  project: Project | null
  setActiveScreen: (s: Screen) => void
}

export default function IngestScreen({ project, setActiveScreen }: Props) {
  // Extraction state lives in context, keyed by project — each project has its
  // own independent slice, so switching projects mid-extraction doesn't lose
  // progress and multiple projects can extract concurrently.
  const ctx = useExtraction(project?.id ?? '')
  const { log, isExtracting, extractDone, extractError, extractRow, rowResult } = ctx

  const [sources,    setSources]    = useState<Source[]>([])
  const [loadingSrc, setLoadingSrc] = useState(false)

  // Upload zone
  const [uploadState,   setUploadState]   = useState<'idle' | 'busy'>('idle')
  const uploadBusy = useRef(false)

  // File preview shown in the extraction progress panel
  const [, setPreviewDataUrl]  = useState<string | null>(null)
  const [, setPreviewFilename] = useState<string | null>(null)

  // Elapsed-time timer
  const startTimeRef    = useRef<number | null>(null)
  const [, setElapsedSecs] = useState(0)

  // Provider selection — read-only here; switched from Settings (see
  // features/usage/components/ApiKeysSection's provider tabs).
  const [activeProvider, setActiveProvider] = useState<'anthropic' | 'gemini' | 'openai' | `custom:${string}`>('anthropic')
  const [settingsOpen, setSettingsOpen] = useState(false)

  // API key modal
  const [apiKeyModal,      setApiKeyModal]      = useState(false)
  const [apiKeyInput,      setApiKeyInput]      = useState('')
  const [apiKeyIsSet,      setApiKeyIsSet]      = useState<boolean | null>(null)
  const [pendingId,        setPendingId]        = useState<number | null>(null)

  // ── Data loading ────────────────────────────────────────────────────────────

  const loadSources = useCallback(async (pid: string) => {
    setLoadingSrc(true)
    try { setSources(await ingestService.getSources(pid)) }
    catch (e) { console.error('get_sources:', e) }
    finally { setLoadingSrc(false) }
  }, [])

  // Reload keyed by project id, not the project object — see ExportScreen's
  // load effect for the full rationale (same pattern across every screen
  // keyed by project).
  useEffect(() => {
    if (!project) return
    // No manual reset needed on project switch — extraction state is keyed by
    // project id (via useExtraction(project.id)), so each project's log/status
    // is already isolated and persists independently across navigation.
    setSources([]); setPendingId(null)
    setPreviewDataUrl(null); setPreviewFilename(null)
    uploadBusy.current = false; setUploadState('idle')
    loadSources(project.id)
  }, [project?.id, loadSources])

  // Provider + API key status. The key check must WAIT for the provider —
  // running both in parallel checked the Anthropic key while a custom
  // provider was active, so a saved custom key read as "no key set" and the
  // modal reappeared on every remount.
  useEffect(() => {
    llmConfigService.getLlmProvider()
      .then(p => {
        const prov = isValidProvider(p) ? p : 'anthropic'
        setActiveProvider(prov)
        return checkApiKeyStatus(prov)
      })
      .catch(() => checkApiKeyStatus('anthropic'))
    // Mount-only — checkApiKeyStatus is a plain (non-memoized) function
    // declared below; adding it here would re-run this effect on every
    // render instead of once on mount, since a fresh reference is created
    // each render.
  }, [])

  // Phase 0: this fetched each provider's plaintext key purely to test it for
  // non-emptiness. One boolean call replaces all four — the secret never
  // needs to be in the renderer to answer "is one set?".
  async function checkApiKeyStatus(provider = activeProvider) {
    try {
      const status = await llmConfigService.getCredentialStatus()
      setApiKeyIsSet(hasCredential(provider, status))
    } catch { setApiKeyIsSet(false) }
  }

  // Provider is switched from Settings now (single source of truth — see
  // ApiKeysSection). Re-read it whenever Settings closes, in case it changed.
  async function refreshProviderStatus() {
    try {
      const p = await llmConfigService.getLlmProvider()
      if (isValidProvider(p)) { setActiveProvider(p); checkApiKeyStatus(p) }
      else { checkApiKeyStatus() }
    } catch { checkApiKeyStatus() }
  }

  // ── Elapsed timer ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (isExtracting) {
      startTimeRef.current = Date.now()
      setElapsedSecs(0)
      const id = setInterval(() => {
        setElapsedSecs(Math.floor((Date.now() - startTimeRef.current!) / 1000))
      }, 1000)
      return () => clearInterval(id)
    }
  }, [isExtracting])

  // ── Reload sources when extraction finishes (success OR failure) ──────────────
  const prevDoneRef  = useRef(false)
  const prevErrorRef = useRef(false)
  useEffect(() => {
    const doneChanged  = extractDone  && !prevDoneRef.current
    const errorChanged = extractError && !prevErrorRef.current
    if ((doneChanged || errorChanged) && project) {
      loadSources(project.id)
      emit('project-updated')
    }
    prevDoneRef.current  = extractDone
    prevErrorRef.current = extractError
  }, [extractDone, extractError, project?.id, loadSources])

  // ── Upload via native Rust command (no Flask) ────────────────────────────────

  function onDragOver(e: React.DragEvent) { e.preventDefault() }
  function onDrop(e: React.DragEvent)     { e.preventDefault(); handleSelectFile() }

  async function handleSelectFile() {
    if (uploadBusy.current) return
    const filePath = await openFileDialog()
    if (!filePath) return
    if (!project) return

    uploadBusy.current = true
    setUploadState('busy')
    try {
      await ingestService.nativeUploadFile(project.id, filePath)
      await loadSources(project.id)
      // We removed auto-run extraction here per user request.
      // User must manually click "Extract" next to the uploaded source.
    } catch (e) { console.error('native_upload_file:', e) }
    finally { uploadBusy.current = false; setUploadState('idle') }
  }

  // ── CLI extraction ───────────────────────────────────────────────────────────

  // keyReady is an explicit override for the save-then-extract path: the
  // caller there has just saved a key, but `apiKeyIsSet` is still false in
  // this closure (setState hasn't flushed), which would bounce straight back
  // into the modal.
  async function startExtraction(sourceId: number, keyReady = apiKeyIsSet) {
    if (!project || isExtracting) return

    if (!keyReady) {
      setPendingId(sourceId); setApiKeyModal(true); return
    }

    // Load file preview
    const src = sources.find(s => s.id === sourceId)
    const fname = src?.filename ?? null
    setPreviewFilename(fname)
    setPreviewDataUrl(null)
    if (fname && /\.(png|jpe?g)$/i.test(fname)) {
      ingestService.getSourceDataUrl(project.id, fname)
        .then(url => setPreviewDataUrl(url))
        .catch(() => {})
    }

    try {
      // Always run the complete pipeline (page-split → CV → LLM stages), not
      // just the LLM half — cached CV output can itself be stale/wrong, so
      // Re-extract shouldn't silently skip re-deriving it. In particular the
      // UNet line detection is what caps how many connections the rest of the
      // pipeline can ever find, so re-running it is the point of a re-extract.
      await ctx.start(sourceId, false)
    } catch (e: unknown) {
      const msg = typeof e === 'string' ? e : JSON.stringify(e)
      console.error('run_extraction error:', msg)
    }
  }

  async function handleApiKeyConfirm() {
    if (!apiKeyInput.trim()) return
    if (activeProvider === 'gemini') {
      await llmConfigService.saveGeminiKey(apiKeyInput.trim())
    } else if (activeProvider === 'openai') {
      await llmConfigService.saveOpenaiKey(apiKeyInput.trim())
    } else if (activeProvider.startsWith('custom:')) {
      const presetId = activeProvider.slice('custom:'.length)
      const rows = await llmConfigService.getCustomProviders().catch(() => [])
      const existingModel = rows.find(r => r.id === presetId)?.model ?? ''
      await llmConfigService.saveCustomProvider(presetId, apiKeyInput.trim(), existingModel)
    } else {
      await llmConfigService.saveApiKey(apiKeyInput.trim())
    }
    setApiKeyIsSet(true)
    setApiKeyModal(false); setApiKeyInput('')
    if (pendingId !== null) { const id = pendingId; setPendingId(null); startExtraction(id, true) }
  }

  async function handleCancel() {
    await ctx.cancel()
  }

  // ── Guards ───────────────────────────────────────────────────────────────────

  if (!project) {
    return <NoProjectState icon="↓" title="No project selected" body="Pick a project to upload drawings or run extraction." />
  }

  const showProgressPanel = isExtracting || extractDone || extractError || log.length > 0

  return (
    <>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div className="ingest-columns">

        {/* ── LEFT: upload zone -or- extraction progress ── */}
        <div>
          {showProgressPanel ? (
            <ExtractionProgressPanel
              isExtracting={isExtracting}
              extractDone={extractDone}
              extractError={extractError}
              log={log}
              onCancel={handleCancel}
              onNewUpload={() => ctx.reset()}
              onViewCanvas={() => setActiveScreen('canvas')}
              onStartRetrofit={() => {
                // Brownfield work runs through the backend agents: switch the
                // Describe screen to agent mode and seed a retrofit prompt.
                try {
                  localStorage.setItem('describe.agentMode', '1')
                  sessionStorage.setItem('describe.prefill',
                    'Retrofit the digitised drawing: add a pressure transmitter package at ')
                } catch { /* storage blocked — Describe still opens */ }
                setActiveScreen('describe')
              }}
            />
          ) : (
            <UploadZone
              activeProvider={activeProvider}
              onOpenSettings={() => setSettingsOpen(true)}
              uploadState={uploadState}
              onSelectFile={handleSelectFile}
              onDragOver={onDragOver}
              onDrop={onDrop}
              sources={sources}
              apiKeyIsSet={apiKeyIsSet}
            />
          )}
        </div>

        {/* ── RIGHT: source documents cards ── */}
        <SourceList
          sources={sources}
          loadingSrc={loadingSrc}
          isExtracting={isExtracting}
          extractRow={extractRow}
          rowResult={rowResult}
          extractDone={extractDone}
          showProgressPanel={showProgressPanel}
          onRefresh={() => loadSources(project.id)}
          onStartExtraction={startExtraction}
          onViewCanvas={() => setActiveScreen('canvas')}
        />
      </div>

      {/* ── API key modal ─────────────────────────────────────────────────────── */}
      {apiKeyModal && (
        <IngestApiKeyModal
          activeProvider={activeProvider}
          apiKeyInput={apiKeyInput}
          setApiKeyInput={setApiKeyInput}
          pendingId={pendingId}
          onConfirm={handleApiKeyConfirm}
          onClose={() => { setApiKeyModal(false); setApiKeyInput('') }}
          onCancel={() => { setApiKeyModal(false); setApiKeyInput(''); setPendingId(null) }}
        />
      )}

      {settingsOpen && (
        <SettingsModal
          onClose={() => { setSettingsOpen(false); refreshProviderStatus() }}
        />
      )}
    </>
  )
}

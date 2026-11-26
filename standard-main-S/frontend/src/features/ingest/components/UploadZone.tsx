import type { DragEvent } from 'react'
import { Spinner } from '../../../shared/components/spinner/Spinner'
import { customProviderLabel } from '../../../domain/llm/customProviderPresets'
import type { Source } from '../types'

const PROVIDER_LABEL: Record<'anthropic' | 'gemini' | 'openai', string> = {
  anthropic: 'Claude', gemini: 'Gemini', openai: 'OpenAI',
}

function providerLabel(p: 'anthropic' | 'gemini' | 'openai' | `custom:${string}`): string {
  return p.startsWith('custom:') ? customProviderLabel(p) : PROVIDER_LABEL[p as 'anthropic' | 'gemini' | 'openai']
}

export function UploadZone({
  activeProvider, onOpenSettings, uploadState, onSelectFile, onDragOver, onDrop,
  sources, apiKeyIsSet,
}: {
  activeProvider: 'anthropic' | 'gemini' | 'openai' | `custom:${string}`
  onOpenSettings: () => void
  uploadState: 'idle' | 'busy'
  onSelectFile: () => void
  onDragOver: (e: DragEvent) => void
  onDrop: (e: DragEvent) => void
  sources: Source[]
  apiKeyIsSet: boolean | null
}) {
  return (
    <>
      {/* Simple header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
          Upload P&amp;ID
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>PDF or image</span>
        {/* Read-only — the provider is chosen in Settings, the single place
            that decides which engine extraction/Describe/etc. actually use.
            Switching it here too was the second copy of that same control,
            which is what let it silently drift out of sync. */}
        <button
          onClick={onOpenSettings}
          title="Change the active provider in Settings"
          style={{
            marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
            padding: '4px 11px', borderRadius: 20, fontSize: 11, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)',
          }}
        >
          <span style={{ fontSize: 10, lineHeight: 1, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Provider:</span>
          <span style={{ fontSize: 11, lineHeight: 1, color: 'var(--text-primary)', fontWeight: 600 }}>{providerLabel(activeProvider)}</span>
        </button>
      </div>

      {/* Drop zone */}
      <div
        className="upload-zone"
        onClick={onSelectFile}
        onDragOver={onDragOver}
        onDrop={onDrop}
        style={{ cursor: uploadState === 'busy' ? 'default' : 'pointer' }}
      >
        {uploadState === 'busy' ? (
          <>
            <div className="upload-zone-icon"><Spinner size={24} /></div>
            <div className="upload-zone-text" style={{ marginTop: 8 }}>Saving file…</div>
          </>
        ) : (
          <>
            <div className="upload-zone-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.7 }}>
                <polyline points="16 16 12 12 8 16"/>
                <line x1="12" y1="12" x2="12" y2="21"/>
                <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
              </svg>
            </div>
            <div className="upload-zone-text">Drag &amp; drop or click to browse</div>
            <div className="upload-zone-hint">PDF · PNG · JPG · Max 50 MB</div>
          </>
        )}
      </div>

      {/* Pending notice */}
      {sources.length > 0 && (() => {
        const pending = sources.filter(s => s.status !== 'complete')
        if (pending.length === 0) return null
        return (
          <div style={{
            marginTop: 10, display: 'flex', alignItems: 'center', gap: 8,
            padding: '9px 13px', borderRadius: 8, fontSize: 12,
            background: 'var(--accent-dim)', border: '1px solid var(--accent-border)',
            color: 'var(--text-secondary)',
          }}>
            <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{pending.length}</span>
            <span>file{pending.length !== 1 ? 's' : ''} uploaded — click <strong>Extract</strong> on the right to begin.</span>
          </div>
        )
      })()}

      {apiKeyIsSet === false && (
        <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--warning)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>⚠</span>
          No {providerLabel(activeProvider)} API key set — click Extract to enter it.
        </div>
      )}
    </>
  )
}

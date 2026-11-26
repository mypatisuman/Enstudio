import { Spinner } from '../../../shared/components/spinner/Spinner'
import type { CardDef } from '../constants'

export function ExportCard({
  card, existingFile, isLoading, errMsg, successFile,
  isNative, nativeGenerating, nativeError, viewLoading,
  onPreviewNative, onPreviewGeneric, onExport,
}: {
  card: CardDef
  existingFile: string | undefined
  isLoading: boolean
  errMsg: string
  successFile: string
  isNative: boolean
  nativeGenerating: boolean
  nativeError: string
  viewLoading: boolean
  onPreviewNative: () => void
  onPreviewGeneric: () => void
  onExport: () => void
}) {
  return (
    <div className="export-card">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
        <span className="export-card-icon" style={{ marginBottom: 0 }}>{card.icon}</span>
        <span className="export-card-title">{card.title}</span>
        <span style={{ marginLeft: 4, fontSize: 10, color: 'var(--success)', fontWeight: 600 }}>● native</span>
        {existingFile && !successFile && (
          <span style={{ marginLeft: 'auto', color: 'var(--success)', fontSize: 16 }}>✓</span>
        )}
        {successFile && (
          <span style={{ marginLeft: 'auto', color: 'var(--success)', fontSize: 13, fontWeight: 600 }}>✓ Saved</span>
        )}
      </div>

      <div className="export-card-desc">{card.desc}</div>

      {/* Static preview snippet for all cards */}
      <div className="export-card-preview">{card.preview}</div>

      {existingFile && !successFile && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Last: {existingFile}</div>
      )}
      {successFile && (
        <div style={{ fontSize: 11, color: 'var(--success)' }}>Exported: {successFile}</div>
      )}
      {isNative && nativeError && (
        <div style={{
          fontSize: 11, color: 'var(--danger)', background: 'rgba(239,68,68,0.08)',
          borderRadius: 4, padding: '4px 8px', lineHeight: 1.5,
        }}>
          {nativeError}
        </div>
      )}
      {errMsg && (
        <div style={{
          fontSize: 11, color: 'var(--danger)', background: 'rgba(239,68,68,0.08)',
          borderRadius: 4, padding: '4px 8px', lineHeight: 1.5,
        }}>
          {errMsg}
        </div>
      )}

      {/* Footer */}
      <div className="export-card-footer" style={{ marginTop: 'auto', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>

        {/* Preview button */}
        {isNative ? (
          <button
            className="btn btn-ghost"
            disabled={nativeGenerating}
            style={{ fontSize: 13 }}
            onClick={onPreviewNative}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {nativeGenerating ? <Spinner size={14} /> : (
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
              )}
              {nativeGenerating ? 'Generating…' : 'Preview'}
            </span>
          </button>
        ) : (
          <button
            className="btn btn-ghost"
            disabled={isLoading || viewLoading}
            onClick={onPreviewGeneric}
            style={{ fontSize: 13 }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {viewLoading ? <Spinner size={14} /> : (
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
              )}
              Preview
            </span>
          </button>
        )}

        {/* Export / Save as */}
        <button
          className="btn btn-primary"
          disabled={isLoading || (isNative && nativeGenerating)}
          onClick={onExport}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          {isLoading ? <Spinner size={14} /> : (
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          )}
          {isLoading ? 'Exporting…' : 'Export'}
        </button>
      </div>
    </div>
  )
}

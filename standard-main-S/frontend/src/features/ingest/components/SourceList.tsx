import { Spinner } from '../../../shared/components/spinner/Spinner'
import type { Source } from '../types'
import { formatDate } from '../utils'

export function SourceList({
  sources, loadingSrc, isExtracting, extractRow, rowResult,
  extractDone, showProgressPanel,
  onRefresh, onStartExtraction, onViewCanvas,
}: {
  sources: Source[]
  loadingSrc: boolean
  isExtracting: boolean
  extractRow: number | null
  rowResult: Record<number, string>
  extractDone: boolean
  showProgressPanel: boolean
  onRefresh: () => void
  onStartExtraction: (sourceId: number) => void
  onViewCanvas: () => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Section header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" style={{ opacity: 0.8 }}>
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
        <span className="section-heading" style={{ margin: 0 }}>
          Source documents
          {sources.length > 0 && (
            <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: 5, textTransform: 'none', letterSpacing: 0 }}>
              — {sources.length} file{sources.length !== 1 ? 's' : ''}
            </span>
          )}
        </span>
        <button className="btn btn-ghost" style={{ marginLeft: 'auto', fontSize: 11, padding: '4px 10px' }}
          disabled={loadingSrc || isExtracting}
          onClick={onRefresh}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          Refresh
        </button>
      </div>

      {loadingSrc ? (
        <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
          <Spinner size={16} />
        </div>
      ) : sources.length === 0 ? (
        <div style={{
          padding: '32px 20px', textAlign: 'center',
          background: 'var(--bg-secondary)', border: '1px dashed var(--border)',
          borderRadius: 'var(--r-lg)', color: 'var(--text-dim)', fontSize: 12,
        }}>
          No sources yet — upload a file on the left.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sources.map(src => {
            const busy   = isExtracting && extractRow === src.id
            const result = rowResult[src.id]
            const isErr  = result?.startsWith('Error:')
            const isImg  = /\.(png|jpe?g)$/i.test(src.filename)
            return (
              <div key={src.id} style={{
                background: 'var(--bg-secondary)',
                border: `1px solid ${busy ? 'var(--accent-border)' : 'var(--border)'}`,
                borderRadius: 'var(--r-md)',
                padding: '12px 14px',
                display: 'flex', alignItems: 'center', gap: 12,
                boxShadow: busy ? 'var(--shadow-glow)' : 'none',
                transition: 'border-color 0.2s, box-shadow 0.2s',
              }}>
                {/* Info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 12.5, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                       title={src.filename}>
                    {src.filename}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                    {isImg ? 'Image' : 'PDF'} · Uploaded {formatDate(src.uploaded)}
                  </div>
                  {result && (
                    <div style={{ fontSize: 10.5, marginTop: 3, color: isErr ? 'var(--danger)' : 'var(--success)' }}>
                      {result}
                    </div>
                  )}
                </div>

                {/* Status */}
                {busy ? (
                  <span style={{ color: 'var(--accent)', fontSize: 11, fontWeight: 600, flexShrink: 0 }}>
                    Extracting…
                  </span>
                ) : src.status === 'complete' ? (
                  <span className="status-badge extracted" style={{ flexShrink: 0, animation: 'badge-pop 0.25s ease' }}>
                    COMPLETE
                  </span>
                ) : (
                  <span className="status-badge pending" style={{ flexShrink: 0 }}>
                    {src.status}
                  </span>
                )}

                {/* Action */}
                <button
                  className="btn btn-ghost"
                  style={{ fontSize: 11, flexShrink: 0, padding: '5px 11px' }}
                  disabled={isExtracting}
                  onClick={() => onStartExtraction(src.id)}
                >
                  {busy ? <Spinner size={10} /> : src.cached ? '↺ Re-extract' : '▶ Extract'}
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Extraction complete CTA */}
      {extractDone && !isExtracting && !showProgressPanel && (
        <div style={{
          padding: '12px 16px', borderRadius: 'var(--r-md)',
          background: 'var(--success-dim)', border: '1px solid rgba(34,197,94,0.22)',
          display: 'flex', alignItems: 'center', gap: 10, fontSize: 12,
          animation: 'fade-up 0.25s ease',
        }}>
          <span style={{ color: 'var(--success)', fontSize: 16 }}>✓</span>
          <span style={{ color: 'var(--text-secondary)', flex: 1 }}>Extraction completed successfully.</span>
          <button className="btn btn-primary" style={{ fontSize: 11.5, padding: '5px 13px' }}
            onClick={onViewCanvas}>
            Preview Results →
          </button>
        </div>
      )}
    </div>
  )
}

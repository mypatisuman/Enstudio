import type { LogEntry } from '../../../state/extraction/types'
import { EntryIcon } from './EntryIcon'
import { ElapsedTimer } from './ElapsedTimer'

export function ExtractionProgressPanel({
  isExtracting, extractDone, extractError, log,
  onCancel, onNewUpload, onViewCanvas, onStartRetrofit,
}: {
  isExtracting: boolean
  extractDone: boolean
  extractError: boolean
  log: LogEntry[]
  onCancel: () => void
  onNewUpload: () => void
  onViewCanvas: () => void
  /** Open Describe in agent mode to retrofit the drawing just digitised. */
  onStartRetrofit?: () => void
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <div className="section-heading" style={{ margin: 0 }}>
          {isExtracting ? 'Extracting…' : extractError ? 'Extraction failed' : extractDone ? 'Extraction complete' : 'Extraction stopped'}
        </div>

        {isExtracting ? (
          <button className="btn btn-ghost" style={{ fontSize: 11, marginLeft: 'auto' }}
            onClick={onCancel}>
            ✕ Cancel
          </button>
        ) : (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            {extractError && log.some(e => String(e.detail).includes('already running')) && (
              <button className="btn btn-ghost" style={{ fontSize: 11, color: 'var(--danger)' }}
                onClick={onCancel}>
                ✕ Cancel
              </button>
            )}
            <button className="btn btn-ghost" style={{ fontSize: 11 }}
              onClick={onNewUpload}>
              ← New upload
            </button>
          </div>
        )}
      </div>

      {/* Log entries */}
      <div style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 8, padding: '10px 14px',
        display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12,
        maxHeight: 320, overflowY: 'auto', overflowX: 'hidden',
        maxWidth: '100%', minWidth: 0,
      }}>
        {log.length === 0 && (
          <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 12 }}>
            Starting…
          </div>
        )}
        {log.map((entry, i) => (
          <div key={`${entry.stage}-${i}`}
            style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0,
                     marginLeft: entry.indent ? 22 : 0 }}>
            {/* Icon */}
            <div style={{ width: 16, flexShrink: 0 }}>
              <EntryIcon status={entry.status} />
            </div>
            {/* Label + detail */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{entry.label}</span>
              {entry.detail && (
                <span style={{
                  color: 'var(--text-muted)', minWidth: 0,
                  overflowWrap: 'anywhere', wordBreak: 'break-word',
                }}>{entry.detail}</span>
              )}
            </div>
            {/* Time */}
            <ElapsedTimer
              startedAt={entry.startedAt}
              durationMs={entry.durationMs}
              status={entry.status}
            />
          </div>
        ))}
      </div>

      {/* Done summary + nav */}
      {extractDone && !isExtracting && (
        <div style={{
          marginTop: 12, padding: '10px 14px',
          background: 'rgba(34,197,94,0.07)', border: '1px solid rgba(34,197,94,0.2)',
          borderRadius: 7, display: 'flex', alignItems: 'center', gap: 10, fontSize: 12,
        }}>
          <span style={{ color: 'var(--success)', fontWeight: 700 }}>✓ Done</span>
          <span style={{ flex: 1 }} />
          {onStartRetrofit && (
            <button className="btn btn-ghost" style={{ fontSize: 11 }}
              onClick={onStartRetrofit}
              title="Add instruments and accessories to this digitised drawing with the brownfield agent">
              Start retrofit →
            </button>
          )}
          <button className="btn btn-ghost" style={{ fontSize: 11 }}
            onClick={onViewCanvas}>
            View on Canvas →
          </button>
        </div>
      )}
    </div>
  )
}

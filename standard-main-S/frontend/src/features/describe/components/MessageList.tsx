import type { RefObject } from 'react'
import { Wand2, CornerUpRight, Image as ImageIcon, FileText } from 'lucide-react'
import { Spinner } from '../../../shared/components/spinner/Spinner'
import { Markdown } from '../../copilot/components/Markdown'
import type { ChatEntry } from '../types'

export function MessageList({
  chat, loading, bottomRef, onCancelDeletes, onConfirmDeletes, onFocusTag,
}: {
  chat: ChatEntry[]
  loading: boolean
  bottomRef: RefObject<HTMLDivElement | null>
  onCancelDeletes: (entryIndex: number) => void
  onConfirmDeletes: (entryIndex: number, tags: string[]) => void
  onFocusTag?: (tag: string) => void
}) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 12 }}>

      {chat.length === 0 && !loading && (
        <div style={{ textAlign: 'center', paddingTop: 60, color: 'var(--text-muted)', fontSize: 13, lineHeight: 2 }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14, opacity: 0.3 }}>
            <Wand2 size={36} strokeWidth={1.3} />
          </div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>Describe mode</div>
          <div>Build the diagram — "add a feed drum V-101 and pump P-101" —</div>
          <div>or ask about it: "find all pumps", "explain FT-101",</div>
          <div>"summarize this drawing", "how many warnings?"</div>
          <div style={{ marginTop: 16, fontSize: 11, color: 'var(--text-muted)' }}>
            Editing, search, explanations and validation — all in one chat.
          </div>
        </div>
      )}

      {chat.map((entry, i) => (
        <div key={i} style={{
          display: 'flex',
          justifyContent: entry.role === 'user' ? 'flex-end' : 'flex-start',
        }}>
          <div style={{
            maxWidth: '75%',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            alignItems: entry.role === 'user' ? 'flex-end' : 'flex-start',
          }}>
            {/* Role label */}
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', paddingInline: 4 }}>
              {entry.role === 'user' ? 'You' : 'AI'}
            </div>

            {/* Bubble */}
            <div style={{
              padding: '10px 14px',
              borderRadius: entry.role === 'user' ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
              background: entry.isError
                ? 'rgba(239,68,68,0.1)'
                : entry.role === 'user'
                  ? 'rgba(109,40,217,0.18)'
                  : 'var(--bg-secondary)',
              border: `1px solid ${
                entry.isError ? 'rgba(239,68,68,0.3)'
                : entry.role === 'user' ? 'rgba(109,40,217,0.3)'
                : 'var(--border)'}`,
              fontSize: 13,
              lineHeight: 1.55,
              color: entry.isError ? 'var(--danger)' : 'var(--text-primary)',
              whiteSpace: entry.answerMarkdown ? 'normal' : 'pre-wrap',
              wordBreak: 'break-word',
            }}>
              {entry.answerMarkdown ? <Markdown text={entry.display} /> : entry.display}
            </div>

            {/* What was attached to this turn — cosmetic only (see ChatEntry.attachments) */}
            {entry.attachments && entry.attachments.length > 0 && (
              <div className="desc-attach-row" style={{ marginTop: -2 }}>
                {entry.attachments.map((a, ai) => (
                  <span key={ai} className="desc-attach-chip desc-attach-chip--static">
                    {a.kind === 'image' ? <ImageIcon size={12} /> : <FileText size={12} />}
                    <span className="desc-attach-name">{a.name}</span>
                  </span>
                ))}
              </div>
            )}

            {/* Clickable search/validation results → focus on Canvas */}
            {entry.results && entry.results.length > 0 && (
              <div className="cop-results" style={{ width: '100%' }}>
                {entry.results.map(r => (
                  <button key={r.tag} className="cop-result" onClick={() => onFocusTag?.(r.tag)} title="Focus on Canvas">
                    <span className="cop-result-tag">{r.title}</span>
                    <span className="cop-result-detail">{r.detail}</span>
                    <CornerUpRight size={13} />
                  </button>
                ))}
              </div>
            )}

            {/* Badge: nodes/edges added, nodes updated */}
            {(entry.nodesAdded ?? 0) + (entry.edgesAdded ?? 0) + (entry.nodesUpdated ?? 0) > 0 && (
              <div style={{ display: 'flex', gap: 6, paddingInline: 4 }}>
                {(entry.nodesAdded ?? 0) > 0 && (
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 99, fontWeight: 600,
                    background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)',
                    color: 'var(--success)',
                  }}>
                    +{entry.nodesAdded} node{entry.nodesAdded !== 1 ? 's' : ''}
                  </span>
                )}
                {(entry.edgesAdded ?? 0) > 0 && (
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 99, fontWeight: 600,
                    background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)',
                    color: '#3b82f6',
                  }}>
                    +{entry.edgesAdded} connection{entry.edgesAdded !== 1 ? 's' : ''}
                  </span>
                )}
                {(entry.nodesUpdated ?? 0) > 0 && (
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 99, fontWeight: 600,
                    background: 'rgba(234,179,8,0.1)', border: '1px solid rgba(234,179,8,0.3)',
                    color: '#eab308',
                  }}>
                    ~{entry.nodesUpdated} updated
                  </span>
                )}
              </div>
            )}

            {/* Pending delete confirmation */}
            {entry.pendingDeletes && !entry.deleteResolution && (
              <div style={{
                display: 'flex', flexDirection: 'column', gap: 8, paddingInline: 4,
                marginTop: 2, padding: '10px 12px', borderRadius: 8,
                background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
              }}>
                <div style={{ fontSize: 12, color: 'var(--text-primary)' }}>
                  Delete <strong>{entry.pendingDeletes.join(', ')}</strong> and its connections?
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }}
                    onClick={() => onCancelDeletes(i)}>
                    Cancel
                  </button>
                  <button className="btn"
                    style={{ fontSize: 12, padding: '4px 10px', background: 'var(--danger)', color: '#fff' }}
                    onClick={() => onConfirmDeletes(i, entry.pendingDeletes!)}>
                    Delete
                  </button>
                </div>
              </div>
            )}
            {entry.pendingDeletes && entry.deleteResolution === 'confirmed' && (
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 99, fontWeight: 600,
                background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
                color: 'var(--danger)', alignSelf: entry.role === 'user' ? 'flex-end' : 'flex-start',
              }}>
                -{entry.nodesDeleted ?? 0} deleted
              </span>
            )}
            {entry.pendingDeletes && entry.deleteResolution === 'cancelled' && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)', paddingInline: 4 }}>
                Deletion cancelled.
              </span>
            )}
          </div>
        </div>
      ))}

      {/* Thinking indicator */}
      {loading && (
        <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
          <div style={{
            padding: '10px 14px', borderRadius: '12px 12px 12px 4px',
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', gap: 8,
            fontSize: 12, color: 'var(--text-muted)',
          }}>
            <Spinner size={12} /> Thinking…
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}

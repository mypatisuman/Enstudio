import { ChevronDown, Plus, Pencil, Trash2 } from 'lucide-react'
import type { DescribeSession } from '../types'

export function SessionToolbar({
  sessions, activeSessionId, sessionMenuOpen, setSessionMenuOpen,
  editingSessionId, setEditingSessionId, editingTitle, setEditingTitle,
  onSelectSession, onSaveTitle, onRequestDelete, onNewChat,
}: {
  sessions: DescribeSession[]
  activeSessionId: number | null
  sessionMenuOpen: boolean
  setSessionMenuOpen: (v: boolean | ((o: boolean) => boolean)) => void
  editingSessionId: number | null
  setEditingSessionId: (id: number | null) => void
  editingTitle: string
  setEditingTitle: (t: string) => void
  onSelectSession: (id: number) => void
  onSaveTitle: (session: DescribeSession) => void
  onRequestDelete: (session: DescribeSession) => void
  onNewChat: () => void
}) {
  return (
    <div style={{
      flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8,
      padding: '10px 24px', borderBottom: '1px solid var(--border)',
    }}>
      <div style={{ position: 'relative', flex: 1, maxWidth: 340 }}>
        <button
          onClick={() => setSessionMenuOpen(o => !o)}
          style={{
            width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 6, color: 'var(--text-primary)', font: 'inherit', fontSize: 12,
            padding: '6px 10px', outline: 'none', cursor: 'pointer',
          }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {activeSessionId == null ? 'New chat' : (sessions.find(s => s.id === activeSessionId)?.title ?? 'New chat')}
          </span>
          <ChevronDown size={14} style={{ flexShrink: 0, opacity: 0.7 }} />
        </button>

        {sessionMenuOpen && (
          <>
            <div style={{ position: 'fixed', inset: 0, zIndex: 40 }} onClick={() => setSessionMenuOpen(false)} />
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              borderRadius: 6, zIndex: 50, maxHeight: 280, overflowY: 'auto',
              boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
            }}>
              {activeSessionId == null && (
                <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--text-primary)', background: 'var(--bg-tertiary)' }}>
                  New chat
                </div>
              )}
              {sessions.map(s => (
                <div
                  key={s.id}
                  onClick={() => { if (editingSessionId !== s.id) { onSelectSession(s.id); setSessionMenuOpen(false) } }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '8px 10px', fontSize: 12, cursor: 'pointer',
                    background: s.id === activeSessionId ? 'var(--bg-tertiary)' : 'transparent',
                    color: 'var(--text-primary)',
                  }}
                >
                  {editingSessionId === s.id ? (
                    <input
                      autoFocus
                      value={editingTitle}
                      onClick={e => e.stopPropagation()}
                      onChange={e => setEditingTitle(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') { e.preventDefault(); onSaveTitle(s) }
                        if (e.key === 'Escape') { e.preventDefault(); setEditingSessionId(null) }
                      }}
                      onBlur={() => onSaveTitle(s)}
                      style={{
                        flex: 1, minWidth: 0, background: 'var(--bg-tertiary)', border: '1px solid var(--accent)',
                        borderRadius: 4, color: 'var(--text-primary)', font: 'inherit', fontSize: 12,
                        padding: '2px 6px', outline: 'none',
                      }}
                    />
                  ) : (
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.title}
                    </span>
                  )}
                  <button
                    onClick={e => { e.stopPropagation(); setEditingSessionId(s.id); setEditingTitle(s.title) }}
                    title="Rename chat"
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                      background: 'transparent', border: 'none', color: 'var(--text-muted)',
                      cursor: 'pointer', padding: 4, borderRadius: 4,
                    }}
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    onClick={e => { e.stopPropagation(); onRequestDelete(s); setSessionMenuOpen(false) }}
                    title="Delete chat"
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                      background: 'transparent', border: 'none', color: 'var(--danger)',
                      cursor: 'pointer', padding: 4, borderRadius: 4,
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      <button
        className="btn btn-ghost"
        style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '6px 10px' }}
        onClick={onNewChat}
      >
        <Plus size={14} /> New chat
      </button>
    </div>
  )
}

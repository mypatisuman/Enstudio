import type { DescribeSession } from '../types'

export function SessionDeleteModal({
  session, onConfirm, onClose,
}: { session: DescribeSession; onConfirm: () => void; onClose: () => void }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
    }} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '28px 28px 24px', width: 380,
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--text-primary)' }}>
          Delete chat?
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          "{session.title}" and its full message history will be permanently deleted. This can't be undone.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn" style={{ background: 'var(--danger)', color: '#fff' }} onClick={onConfirm}>
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

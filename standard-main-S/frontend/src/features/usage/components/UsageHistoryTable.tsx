import { RefreshCw, Trash2 } from 'lucide-react'
import type { UsageRecord } from '../types'
import { fmtTime } from '../utils'

export function UsageHistoryTable({
  usageHistory, loading, totalTokensAll, totalCostAll, onRefresh, onSelectProject, onDeleteProject,
}: {
  usageHistory: UsageRecord[]
  loading: boolean
  totalTokensAll: number
  totalCostAll: number
  onRefresh: () => void
  onSelectProject: (row: UsageRecord) => void
  onDeleteProject: (row: UsageRecord) => void
}) {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* No section heading here — the modal's own "Usage & Cost History"
          title already covers it; this repeated it as "Usage History". */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 16 }}>
        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          Total Tokens: <strong style={{ color: 'var(--text-primary)' }}>{totalTokensAll.toLocaleString()}</strong> &nbsp;|&nbsp;
          Total Estimated Cost: <strong style={{ color: 'var(--text-primary)' }}>${totalCostAll.toFixed(4)}</strong>
        </span>
        <button
          onClick={onRefresh}
          title="Refresh usage data"
          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', padding: 4 }}
        >
          <RefreshCw size={14} />
        </button>
      </div>

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading history...</div>
        ) : usageHistory.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No extraction usage history found.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
            <thead>
              <tr style={{ background: 'var(--bg-tertiary)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--text-secondary)' }}>Project</th>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--text-secondary)', width: 120 }}>Tokens</th>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--text-secondary)', width: 120 }}>Est. Cost</th>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--text-secondary)', width: 180 }}>Last Extraction</th>
                <th style={{ padding: '12px 16px', width: 40 }} />
              </tr>
            </thead>
            <tbody>
              {usageHistory.map(row => (
                <tr
                  key={row.pid}
                  style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer', transition: 'background 0.2s' }}
                  onClick={() => onSelectProject(row)}
                  title="Click to view extraction history"
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-tertiary)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '12px 16px', color: 'var(--text-primary)' }}>
                    <div style={{ fontWeight: 500 }}>{row.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{row.pid} &middot; {row.scans?.length || 0} extractions</div>
                  </td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-primary)' }}>{row.total_tokens.toLocaleString()}</td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-primary)' }}>${row.total_cost.toFixed(4)}</td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-muted)' }}>{row.last_scan ? fmtTime(row.last_scan) : 'Never'}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <button
                      onClick={e => { e.stopPropagation(); onDeleteProject(row) }}
                      title="Delete this project's usage history"
                      aria-label="Delete project usage history"
                      style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', padding: 4 }}
                      onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
                      onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

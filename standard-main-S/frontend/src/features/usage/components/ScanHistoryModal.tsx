import { createPortal } from 'react-dom'
import { X, Trash2 } from 'lucide-react'
import type { UsageRecord } from '../types'
import { fmtTime } from '../utils'

export function ScanHistoryModal({
  project, onClose, onDeleteScan,
}: {
  project: UsageRecord
  onClose: () => void
  onDeleteScan: (pid: string, scanIndex: number) => void
}) {
  return createPortal(
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
    }} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '24px 24px 20px', width: '90%', maxWidth: 700, maxHeight: '80vh',
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
            Extraction History: {project.name}
          </div>
          <button className="modal-x" onClick={onClose} aria-label="Close"><X size={17} /></button>
        </div>

        <div style={{ overflowY: 'auto', flex: 1, background: 'var(--bg-tertiary)', borderRadius: 8, border: '1px solid var(--border)' }}>
          {project.scans && project.scans.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--text-secondary)' }}>Date</th>
                  <th style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--text-secondary)' }}>File</th>
                  <th style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--text-secondary)' }}>Model</th>
                  <th style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--text-secondary)' }}>Tokens</th>
                  <th style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--text-secondary)' }}>Cost</th>
                  <th style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', width: 36 }} />
                </tr>
              </thead>
              <tbody>
                {[...project.scans].reverse().map((scan, i) => {
                  // The array is reversed for display (newest first); the backend
                  // stores/indexes scans in original (oldest-first) order, so the
                  // index to delete is the mirror of the display index — using
                  // `i` directly here would silently delete the WRONG scan.
                  const originalIndex = project.scans.length - 1 - i
                  return (
                    <tr key={i} style={{ borderBottom: i === project.scans.length - 1 ? 'none' : '1px solid var(--border)' }}>
                      <td style={{ padding: '10px 14px', color: 'var(--text-primary)' }}>{fmtTime(scan.timestamp)}</td>
                      <td style={{ padding: '10px 14px', color: 'var(--text-primary)' }}>{scan.filename} (Pass {scan.pass})</td>
                      <td style={{ padding: '10px 14px', color: 'var(--text-primary)' }}>{scan.model || scan.provider}</td>
                      <td style={{ padding: '10px 14px', color: 'var(--text-primary)' }}>{(scan.tokens_in + scan.tokens_out).toLocaleString()}</td>
                      <td style={{ padding: '10px 14px', color: 'var(--text-primary)' }}>${scan.cost_usd.toFixed(4)}</td>
                      <td style={{ padding: '10px 14px' }}>
                        <button
                          onClick={() => onDeleteScan(project.pid, originalIndex)}
                          title="Delete this extraction record"
                          aria-label="Delete extraction record"
                          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', padding: 2 }}
                          onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
                          onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>
              No historical scan details found.
            </div>
          )}
        </div>
      </div>
    </div>, document.body,
  )
}

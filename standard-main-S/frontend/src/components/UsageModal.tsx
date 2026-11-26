import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { listen } from '@tauri-apps/api/event'
import { toast } from 'sonner'
import { X, BarChart2 } from 'lucide-react'
import { storedUserId } from '../services/authApi'
import * as usageService from '../services/usage'
import type { UsageRecord } from '../features/usage/types'
import { UsageHistoryTable } from '../features/usage/components/UsageHistoryTable'
import { ScanHistoryModal } from '../features/usage/components/ScanHistoryModal'
import ConfirmModal from './ConfirmModal'

/** Usage & cost history as a popup — was a full navigated screen (Screen
 * 'usage'), moved to a modal so it opens over whatever you're doing instead
 * of leaving your current screen. Same data/logic as before, just re-homed. */
export function UsageModal({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const dismiss = () => { setOpen(false); setTimeout(onClose, 160) }

  const [usageHistory, setUsageHistory] = useState<UsageRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedProject, setSelectedProject] = useState<UsageRecord | null>(null)

  // Pending deletes — set by clicking a trash icon, only actually deleted once
  // the in-app ConfirmModal below is confirmed (replaces window.confirm(),
  // which shows a plain OS dialog that doesn't match the app).
  const [pendingDeleteProject, setPendingDeleteProject] = useState<UsageRecord | null>(null)
  const [pendingDeleteScan, setPendingDeleteScan] = useState<{ pid: string; scanIndex: number } | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function loadUsage(): Promise<UsageRecord[]> {
    try {
      setLoading(true)
      const history = await usageService.getUsageHistory(storedUserId()) as unknown as UsageRecord[]
      setUsageHistory(history || [])
      return history || []
    } catch (e) {
      console.error('Failed to load usage history', e)
      toast.error('Failed to load usage history')
      return []
    } finally {
      setLoading(false)
    }
  }

  async function confirmDeleteProject() {
    const row = pendingDeleteProject
    if (!row) return
    setDeleting(true)
    try {
      await usageService.deleteProjectUsage(row.pid)
      toast.success(`Deleted usage history for ${row.name}`)
      await loadUsage()
      // Close the drill-down if it was showing the project we just wiped.
      setSelectedProject(prev => (prev && prev.pid === row.pid) ? null : prev)
      setPendingDeleteProject(null)
    } catch (e) {
      console.error('Failed to delete project usage', e)
      toast.error('Failed to delete project usage')
    } finally {
      setDeleting(false)
    }
  }

  async function confirmDeleteScan() {
    const pending = pendingDeleteScan
    if (!pending) return
    setDeleting(true)
    try {
      await usageService.deleteUsageScan(pending.pid, pending.scanIndex)
      toast.success('Extraction record deleted')
      const history = await loadUsage()
      // Keep the drill-down open but refreshed, so the deleted row disappears
      // immediately instead of showing stale data until the modal is reopened.
      setSelectedProject(prev => (prev && prev.pid === pending.pid) ? (history.find(r => r.pid === pending.pid) ?? null) : prev)
      setPendingDeleteScan(null)
    } catch (e) {
      console.error('Failed to delete scan', e)
      toast.error('Failed to delete extraction record')
    } finally {
      setDeleting(false)
    }
  }

  useEffect(() => {
    loadUsage()
    const unlisten = listen('extraction-progress', (ev: { payload: { stage?: string } }) => {
      if (ev.payload?.stage === 'done' || ev.payload?.stage === 'finished') {
        loadUsage()
      }
    })
    return () => { unlisten.then(fn => fn()) }
  }, [])

  const totalTokensAll = usageHistory.reduce((sum, r) => sum + r.total_tokens, 0)
  const totalCostAll = usageHistory.reduce((sum, r) => sum + r.total_cost, 0)

  return createPortal(
    <div
      className={`modal-backdrop${open ? ' open' : ''}`}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
        padding: 40,
      }}
      onClick={e => { if (e.target === e.currentTarget) dismiss() }}
    >
      <div className="modal-dialog" style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '22px 22px 18px', width: '100%', maxWidth: 900,
        maxHeight: '86vh', overflowY: 'auto',
        display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
            <BarChart2 size={18} className="text-accent" /> Usage &amp; Cost History
          </div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        <UsageHistoryTable
          usageHistory={usageHistory}
          loading={loading}
          totalTokensAll={totalTokensAll}
          totalCostAll={totalCostAll}
          onRefresh={loadUsage}
          onSelectProject={setSelectedProject}
          onDeleteProject={setPendingDeleteProject}
        />

        {selectedProject && (
          <ScanHistoryModal
            project={selectedProject}
            onClose={() => setSelectedProject(null)}
            onDeleteScan={(pid, scanIndex) => setPendingDeleteScan({ pid, scanIndex })}
          />
        )}
      </div>

      {pendingDeleteProject && (
        <ConfirmModal
          title="Delete project usage history?"
          body={
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              This deletes all {pendingDeleteProject.scans?.length || 0} extraction record(s) and cost totals for{' '}
              <strong style={{ color: 'var(--text-primary)' }}>{pendingDeleteProject.name}</strong>.
              The project itself and its extracted data are not affected — only this usage history. This cannot be undone.
            </div>
          }
          confirmLabel={deleting ? 'Deleting…' : 'Delete'}
          confirmDisabled={deleting}
          confirmDanger
          zIndex={10001}
          onConfirm={confirmDeleteProject}
          onCancel={() => setPendingDeleteProject(null)}
        />
      )}

      {pendingDeleteScan && (
        <ConfirmModal
          title="Delete this extraction record?"
          body={
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              This removes it from the usage history and recalculates the project's totals. This cannot be undone.
            </div>
          }
          confirmLabel={deleting ? 'Deleting…' : 'Delete'}
          confirmDisabled={deleting}
          confirmDanger
          zIndex={10001}
          onConfirm={confirmDeleteScan}
          onCancel={() => setPendingDeleteScan(null)}
        />
      )}
    </div>,
    document.body,
  )
}

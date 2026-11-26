import { CheckCircle2, XCircle, ListChecks, X } from 'lucide-react'

export function ReviewToolbar({
  bulkLoading, filteredCount, selectedCount, accepted, instrumentCount,
  onSelectAllFiltered, onClearSelection, onAcceptSelected, onRejectSelected,
}: {
  bulkLoading: boolean
  filteredCount: number
  selectedCount: number
  accepted: number
  instrumentCount: number
  onSelectAllFiltered: () => void
  onClearSelection: () => void
  onAcceptSelected: () => void
  onRejectSelected: () => void
}) {
  const hasSelection = selectedCount > 0
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      {/* Select all visible / filtered */}
      <button
        className="btn btn-ghost"
        disabled={filteredCount === 0}
        onClick={onSelectAllFiltered}
        style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 5 }}
        title="Select all rows currently shown"
      >
        <ListChecks size={13} strokeWidth={2} /> Select all visible ({filteredCount})
      </button>

      {hasSelection && (
        <>
          <span className="rv-selcount">{selectedCount} selected</span>
          <button
            className="btn btn-accept"
            disabled={bulkLoading}
            onClick={onAcceptSelected}
            style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 5 }}
          >
            {bulkLoading ? '…' : <><CheckCircle2 size={13} strokeWidth={2} /> Accept selected</>}
          </button>
          <button
            className="btn btn-reject"
            disabled={bulkLoading}
            onClick={onRejectSelected}
            style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 5 }}
          >
            {bulkLoading ? '…' : <><XCircle size={13} strokeWidth={2} /> Reject selected</>}
          </button>
          <button
            className="btn btn-ghost"
            onClick={onClearSelection}
            style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}
            title="Clear selection"
          >
            <X size={13} /> Clear
          </button>
        </>
      )}

      <div style={{ flex: 1 }} />

      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        {accepted}/{instrumentCount} accepted
        {accepted > 0 && instrumentCount > 0 && (
          <span style={{ marginLeft: 6, color: 'var(--success)' }}>
            ({Math.round(accepted / instrumentCount * 100)}%)
          </span>
        )}
      </span>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>
        Double-click Equip ref or Desc to edit
      </span>
    </div>
  )
}

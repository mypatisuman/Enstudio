import type { RefObject, KeyboardEvent } from 'react'
import type { Instrument } from '../../../services/review'
import { TypeBadge } from '../../../shared/components/status/TypeBadge'
import { ConfidenceBadge } from '../ConfidenceBadge'

export type EditField = 'equipment_ref' | 'description'
export interface EditCell { tag: string; field: EditField }

function statusStyle(s: string): React.CSSProperties {
  switch (s) {
    case 'accepted': return { background: 'rgba(34,197,94,0.07)' }
    case 'rejected': return { background: 'rgba(239,68,68,0.07)' }
    default:         return {}
  }
}

function statusBadge(s: string) {
  const map: Record<string, string> = {
    accepted: 'var(--success)',
    rejected: 'var(--danger)',
    pending:  'var(--text-muted)',
  }
  return (
    <span style={{
      color: map[s] ?? 'var(--text-muted)',
      fontWeight: 600, fontSize: 11,
      textTransform: 'uppercase' as const, letterSpacing: '0.05em',
    }}>
      {s}
    </span>
  )
}

export function InstrumentTable({
  filtered, eff, editCell, editValue, setEditValue, editRef,
  startEdit, commitEdit, handleEditKey, onReview,
  selected, onToggleSelect, allFilteredSelected, onToggleAll,
  emptyTitle, emptyBody, onRowFocus, showConfidence, showDrawing, showArea,
}: {
  filtered: Instrument[]
  eff: (i: Instrument) => Instrument
  editCell: EditCell | null
  editValue: string
  setEditValue: (v: string) => void
  editRef: RefObject<HTMLInputElement | null>
  startEdit: (tag: string, field: EditField, current: string) => void
  commitEdit: () => void
  handleEditKey: (e: KeyboardEvent) => void
  onReview: (tag: string, action: 'accepted' | 'rejected') => void
  selected: Set<string>
  onToggleSelect: (tag: string) => void
  allFilteredSelected: boolean
  onToggleAll: () => void
  emptyTitle: string
  emptyBody: string
  onRowFocus: (tag: string) => void
  showConfidence: boolean
  showDrawing: boolean
  showArea: boolean
}) {
  // Always: checkbox, tag, type, equip-ref, description, status, actions (7).
  const colCount = 7 + (showDrawing ? 1 : 0) + (showArea ? 1 : 0) + (showConfidence ? 1 : 0)
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th style={{ width: 32 }}>
              <input
                type="checkbox"
                aria-label="Select all visible"
                checked={allFilteredSelected}
                onChange={onToggleAll}
                disabled={filtered.length === 0}
              />
            </th>
            <th>Tag</th>
            <th>Type</th>
            {showDrawing && <th>Drawing</th>}
            <th>Equip ref</th>
            <th>Description</th>
            {showArea && <th>Area</th>}
            {showConfidence && <th>Conf</th>}
            <th>Status</th>
            <th style={{ width: 72 }}></th>
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 && (
            <tr>
              <td colSpan={colCount}>
                <div className="rv-empty">
                  <div className="rv-empty__title">{emptyTitle}</div>
                  <div className="rv-empty__body">{emptyBody}</div>
                </div>
              </td>
            </tr>
          )}
          {filtered.map(row => {
            const e     = eff(row)
            const isEditingEquipRef = editCell?.tag === row.tag && editCell?.field === 'equipment_ref'
            const isEditingDesc     = editCell?.tag === row.tag && editCell?.field === 'description'
            const isSel = selected.has(row.tag)

            return (
              <tr key={row.tag} className={isSel ? 'rv-row--sel' : undefined} style={statusStyle(e.review_status)}>

                {/* Selection checkbox */}
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.tag}`}
                    checked={isSel}
                    onChange={() => onToggleSelect(row.tag)}
                  />
                </td>

                {/* Tag — click to locate on canvas */}
                <td>
                  <button
                    className="rv-tag-link tag-mono"
                    title="Locate on canvas"
                    onClick={() => onRowFocus(row.tag)}
                  >
                    {row.tag}
                  </button>
                </td>

                {/* Type */}
                <td>
                  <TypeBadge label={row.kind_detail || row.type || '—'} />
                </td>

                {/* Drawing */}
                {showDrawing && (
                  <td style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                    {row.drawing || '—'}
                  </td>
                )}

                {/* Equip ref — double-click to edit */}
                <td>
                  {isEditingEquipRef ? (
                    <input
                      ref={editRef}
                      className="cell-input"
                      value={editValue}
                      onChange={ev => setEditValue(ev.target.value)}
                      onBlur={commitEdit}
                      onKeyDown={handleEditKey}
                    />
                  ) : (
                    <span
                      className={e.equipment_ref ? 'tag-mono' : ''}
                      style={{
                        color: e.equipment_ref ? 'var(--text-secondary)' : 'var(--text-muted)',
                        cursor: 'text', fontSize: 12,
                        display: 'block', minWidth: 40,
                      }}
                      title="Double-click to edit"
                      onDoubleClick={() => startEdit(row.tag, 'equipment_ref', e.equipment_ref)}
                    >
                      {e.equipment_ref || '—'}
                    </span>
                  )}
                </td>

                {/* Description — double-click to edit */}
                <td style={{ maxWidth: 160 }}>
                  {isEditingDesc ? (
                    <input
                      ref={editRef}
                      className="cell-input"
                      value={editValue}
                      onChange={ev => setEditValue(ev.target.value)}
                      onBlur={commitEdit}
                      onKeyDown={handleEditKey}
                    />
                  ) : (
                    <span
                      style={{
                        color: e.description ? 'var(--text-secondary)' : 'var(--text-muted)',
                        fontSize: 11, cursor: 'text',
                        display: 'block',
                        overflow: 'hidden', textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap', maxWidth: 150,
                      }}
                      title={e.description || 'Double-click to add description'}
                      onDoubleClick={() => startEdit(row.tag, 'description', e.description)}
                    >
                      {e.description || '—'}
                    </span>
                  )}
                </td>

                {/* Area */}
                {showArea && (
                  <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                    {row.area || '—'}
                  </td>
                )}

                {/* Confidence badge — only when the data model carries it */}
                {showConfidence && (
                  <td>
                    <ConfidenceBadge confidence={row.confidence} type={row.kind_detail || row.type} drawing={row.drawing} />
                  </td>
                )}

                {/* Status badge */}
                <td>{statusBadge(e.review_status)}</td>

                {/* Accept / Reject action buttons */}
                <td>
                  <div className="action-cell">
                    <button
                      className={`btn ${e.review_status === 'accepted' ? 'btn-accept' : 'btn-ghost'}`}
                      style={{ padding: '3px 7px', fontSize: 13, lineHeight: 1 }}
                      title={e.review_status === 'accepted' ? 'Un-accept' : 'Accept'}
                      onClick={() => onReview(row.tag, 'accepted')}
                    >
                      ✓
                    </button>
                    <button
                      className={`btn ${e.review_status === 'rejected' ? 'btn-reject' : 'btn-ghost'}`}
                      style={{ padding: '3px 7px', fontSize: 13, lineHeight: 1 }}
                      title={e.review_status === 'rejected' ? 'Un-reject' : 'Reject'}
                      onClick={() => onReview(row.tag, 'rejected')}
                    >
                      ✗
                    </button>
                  </div>
                </td>

              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

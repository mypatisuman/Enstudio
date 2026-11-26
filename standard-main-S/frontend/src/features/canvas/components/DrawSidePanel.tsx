import React, { useState, useEffect } from 'react'
import * as graphService from '../../../services/graph'
import * as canvasService from '../../../services/canvas'
import * as reviewService from '../../../services/review'
import { isInstrument } from '../../../domain/isa/instrument'
import type { CData } from '../types'

export function DrawSidePanel({ node, open, projectId, isExtracted, onClose, onSave, onDelete }: {
  node: CData
  open: boolean
  projectId: string
  isExtracted?: boolean
  onClose: () => void
  onSave: (updated: CData) => void
  onDelete: () => void
}) {
  const nodeId = String((node as Record<string, unknown>).nodeId ?? (node as Record<string, unknown>).id ?? '')
  const [tag, setTag] = useState(String(node.label))
  const [kind, setKind] = useState(String(node.type || node.kind))
  const [category, setCategory] = useState(isInstrument(String(node.kind)) ? 'Instrument' : 'Equipment')
  const [categoryFocused, setCategoryFocused] = useState(false)
  const [kindFocused, setKindFocused] = useState(false)
  const [area] = useState(String(node.area))
  // Which equipment/vendor-package this instrument is mounted on — packVendorPackages()
  // in extractedLayout.ts nests the node inside its parent box when this matches a
  // vendor_package/package tag, instead of the default nearby+association-line placement.
  const [equipmentRef, setEquipmentRef] = useState(String(node.equipment_ref ?? ''))

  const [dbKinds, setDbKinds] = useState<{ instruments: string[], equipment: string[] }>({ instruments: [], equipment: [] })
  useEffect(() => {
    canvasService.getNodeKinds()
      .then(setDbKinds)
      .catch(console.error)
  }, [])

  function onCategoryChange(c: string) {
    setCategory(c)
  }

  const CATEGORY_OPTIONS = ['Instrument', 'Equipment']
  const displayedCategories = CATEGORY_OPTIONS.filter(c => c.toLowerCase().includes(category.toLowerCase()))

  const filteredKinds = category === 'Instrument' ? dbKinds.instruments : dbKinds.equipment

  const displayedKinds = filteredKinds.filter(k => k.toLowerCase().includes(kind.toLowerCase()))
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [err, setErr] = useState('')

  async function save() {
    if (!nodeId || !tag.trim()) { setErr('Tag cannot be empty'); return }
    setSaving(true); setErr('')
    try {
      await graphService.updateNode(projectId, nodeId, tag.trim(), kind, area, '')
      // equipment_ref lives on the instruments table (not nodes) — separate write.
      if (category === 'Instrument') {
        await reviewService.updateInstrument(projectId, tag.trim(), 'equipment_ref', equipmentRef.trim())
      }
      onSave({ ...node, label: tag.trim(), kind, kind_detail: kind, area, equipment_ref: equipmentRef.trim() })
    } catch (e: unknown) { setErr(typeof e === 'string' ? e : String(e)) }
    finally { setSaving(false) }
  }

  async function del() {
    if (!nodeId) return
    if (!window.confirm(`Delete ${String(node.label)}?`)) return
    setDeleting(true)
    try {
      await graphService.deleteNode(projectId, nodeId)
      onDelete()
    } catch (e: unknown) { setErr(typeof e === 'string' ? e : String(e)) }
    finally { setDeleting(false) }
  }

  const fieldStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box',
    background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
    borderRadius: 5, color: 'var(--text-primary)', font: 'inherit',
    fontSize: 12, padding: '5px 8px', outline: 'none',
  }
  const labelStyle: React.CSSProperties = {
    fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
    letterSpacing: '0.06em', color: 'var(--text-muted)',
    display: 'block', marginBottom: 3,
  }

  return (
    <div className={`side-panel${open ? ' open' : ''}`} style={{ width: 240, flexShrink: 0, borderLeft: '1px solid var(--border)', background: 'var(--bg-secondary)', padding: '14px 12px', display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-primary)', flex: 1 }}>Edit node</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16, padding: 2 }}>×</button>
      </div>
      <div>
        <label style={labelStyle}>Tag {isExtracted ? '(Read-only)' : ''}</label>
        <input type="text" value={tag} onChange={e => { setTag(e.target.value); setErr('') }}
          onKeyDown={e => { if (e.key === 'Enter') save() }} style={fieldStyle} disabled={isExtracted} />
      </div>
      <div style={{ position: 'relative' }}>
        <label style={labelStyle}>Category</label>
        <input
          type="text"
          value={category}
          onChange={e => onCategoryChange(e.target.value)}
          onFocus={() => setCategoryFocused(true)}
          onBlur={() => setTimeout(() => setCategoryFocused(false), 150)}
          style={fieldStyle}
        />
        {categoryFocused && displayedCategories.length > 0 && (
          <div style={{
            position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: '0 0 5px 5px', maxHeight: 150, overflowY: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.2)'
          }}>
            {displayedCategories.map(c => (
              <div
                key={c}
                onMouseDown={(e) => { e.preventDefault(); onCategoryChange(c); setCategoryFocused(false); }}
                style={{
                  padding: '6px 10px', fontSize: 12, cursor: 'pointer',
                  color: 'var(--text-primary)', borderBottom: '1px solid var(--border)'
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-tertiary)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                {c}
              </div>
            ))}
          </div>
        )}
      </div>
      <div style={{ position: 'relative' }}>
        <label style={labelStyle}>Type</label>
        <input
          type="text"
          value={kind}
          onChange={e => setKind(e.target.value)}
          onFocus={() => setKindFocused(true)}
          onBlur={() => setTimeout(() => setKindFocused(false), 150)}
          style={fieldStyle}
        />
        {kindFocused && displayedKinds.length > 0 && (
          <div style={{
            position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: '0 0 5px 5px', maxHeight: 150, overflowY: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.2)'
          }}>
            {displayedKinds.map(k => (
              <div
                key={k}
                onMouseDown={(e) => { e.preventDefault(); setKind(k); setKindFocused(false); }}
                style={{
                  padding: '6px 10px', fontSize: 12, cursor: 'pointer',
                  color: 'var(--text-primary)', borderBottom: '1px solid var(--border)'
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-tertiary)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                {k.replace(/_/g, ' ')}
              </div>
            ))}
          </div>
        )}
      </div>
      {category === 'Instrument' && (
        <div>
          <label style={labelStyle}>Equipment ref</label>
          <input type="text" value={equipmentRef}
            onChange={e => setEquipmentRef(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') save() }}
            placeholder="e.g. GCV-XXXX — set to a vendor package tag to nest inside it"
            style={fieldStyle} />
        </div>
      )}
      {err && <div style={{ fontSize: 10, color: 'var(--danger)' }}>{err}</div>}
      <div style={{ display: 'flex', gap: 7, marginTop: 2 }}>
        <button className="btn btn-primary" style={{ flex: 1, fontSize: 11 }} disabled={saving || deleting} onClick={save}>
          {saving ? '…' : 'Save'}
        </button>
        <button className="btn btn-ghost" style={{ fontSize: 11, color: 'var(--danger)', border: '1px solid rgba(239,68,68,0.3)' }}
          disabled={saving || deleting} onClick={del} title="Delete node">
          {deleting ? '…' : '🗑'}
        </button>
      </div>
    </div>
  )
}

import { useState, useRef, useEffect } from 'react'
import type { Project } from '../../../App'
import * as graphService from '../../../services/graph'
import { TAG_PREFIXES } from '../../../domain/isa/classification'

export function TagInputModal({ kind, project, onDone, onCancel }: {
  kind: string
  project: Project
  onDone: (tag: string, nodeId: string) => void
  onCancel: () => void
}) {
  const [tag, setTag] = useState(TAG_PREFIXES[kind] ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const ref = useRef<HTMLInputElement>(null)
  // Mount-only: focus + place the cursor after the pre-filled prefix once,
  // when the modal opens. `tag.length` is deliberately NOT a dependency —
  // tracking it would re-run setSelectionRange on every keystroke as the
  // user types, yanking their cursor back to the end mid-edit.
  useEffect(() => { ref.current?.focus(); ref.current?.setSelectionRange(tag.length, tag.length) }, [])

  async function confirm() {
    const t = tag.trim()
    if (!t) { setErr('Enter a tag name'); return }
    setBusy(true); setErr('')
    try {
      const result = await graphService.batchInsertNodes(
        project.id, JSON.stringify([{ tag: t, kind, area: '', description: '' }])
      )
      if (!result.ids.length) { setErr('Tag already exists'); setBusy(false); return }
      onDone(t, result.ids[0].id)
    } catch (e: unknown) { setErr(typeof e === 'string' ? e : String(e)); setBusy(false) }
  }

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)' }}
      onClick={e => { if (e.target === e.currentTarget) onCancel() }}>
      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 10, padding: '18px 20px', width: 280, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>
          Add {kind.replace(/_/g, ' ')}
        </div>
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Tag</div>
          <input ref={ref} type="text" value={tag} placeholder="V-101"
            onChange={e => { setTag(e.target.value); setErr('') }}
            onKeyDown={e => { if (e.key === 'Enter') confirm(); if (e.key === 'Escape') onCancel() }}
            style={{ width: '100%', boxSizing: 'border-box', background: 'var(--bg-tertiary)', border: `1px solid ${err ? 'var(--danger)' : 'var(--border)'}`, borderRadius: 6, color: 'var(--text-primary)', font: 'inherit', fontSize: 13, padding: '7px 10px', outline: 'none' }} />
          {err && <div style={{ fontSize: 10, color: 'var(--danger)', marginTop: 3 }}>{err}</div>}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!tag.trim() || busy} onClick={confirm}>
            {busy ? 'Adding…' : 'Add →'}
          </button>
        </div>
      </div>
    </div>
  )
}

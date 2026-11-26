// Plant hierarchy tree for the active project (site > plant > unit > area >
// system > subsystem). Selecting an entry filters the Canvas to the nodes
// assigned to it or anything beneath it; selecting it again clears the filter.

import { useCallback, useEffect, useMemo, useState } from 'react'
import * as hierarchyService from '../../services/hierarchy'
import type { HierarchyNode, HierarchyTree } from '../../services/hierarchy'
import { emitHierarchyFilter, onGraphChanged } from '../../shared/graphEvents'

function descendantIds(node: HierarchyNode, out = new Set<number>()): Set<number> {
  out.add(node.id)
  node.children.forEach(c => descendantIds(c, out))
  return out
}

function findNode(nodes: HierarchyNode[], id: number): HierarchyNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const hit = findNode(n.children, id)
    if (hit) return hit
  }
  return null
}

export function HierarchyPanel({ projectId }: { projectId: string }) {
  const [tree, setTree] = useState<HierarchyTree | null>(null)
  const [assignment, setAssignment] = useState<Record<string, number>>({})
  const [selected, setSelected] = useState<number | null>(null)
  const [open, setOpen] = useState(true)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ area: '', system: '', subsystem: '' })
  const [error, setError] = useState('')

  const fetchTree = useCallback(
    () => Promise.all([
      hierarchyService.getHierarchy(projectId),
      hierarchyService.getNodeHierarchy(projectId),
    ]),
    [projectId],
  )

  const load = useCallback(() => fetchTree()
    .then(([t, a]) => { setTree(t); setAssignment(a); setError('') })
    .catch(e => setError(typeof e === 'string' ? e : 'Could not load the plant hierarchy')),
  [fetchTree])

  // The Sidebar keys this panel by project id, so selection state starts fresh
  // for every project. State is only set from promise callbacks, and a late
  // response for a project the user already left is discarded.
  useEffect(() => {
    let cancelled = false
    emitHierarchyFilter({ projectId, nodeIds: null })
    fetchTree()
      .then(([t, a]) => { if (!cancelled) { setTree(t); setAssignment(a); setError('') } })
      .catch(e => { if (!cancelled) setError(typeof e === 'string' ? e : 'Could not load the plant hierarchy') })
    return () => { cancelled = true }
  }, [projectId, fetchTree])

  useEffect(() => onGraphChanged(d => { if (d.projectId === projectId) load() }), [projectId, load])

  const select = useCallback((id: number) => {
    if (!tree) return
    if (selected === id) {
      setSelected(null)
      emitHierarchyFilter({ projectId, nodeIds: null })
      return
    }
    const node = findNode(tree.roots, id)
    if (!node) return
    const ids = descendantIds(node)
    const nodeIds = Object.entries(assignment).filter(([, h]) => ids.has(h)).map(([n]) => n)
    setSelected(id)
    emitHierarchyFilter({ projectId, nodeIds, label: node.name })
  }, [tree, selected, assignment, projectId])

  const create = async () => {
    if (!form.system.trim() || !form.subsystem.trim()) {
      setError('System and subsystem names are required')
      return
    }
    try {
      await hierarchyService.createSubsystem(projectId, form.system.trim(), form.subsystem.trim(), form.area.trim())
      setForm({ area: '', system: '', subsystem: '' })
      setAdding(false)
      await load()
    } catch (e) {
      setError(typeof e === 'string' ? e : 'Could not create the subsystem')
    }
  }

  const empty = useMemo(() => !tree || tree.roots.length === 0, [tree])

  const renderNode = (n: HierarchyNode, depth: number) => (
    <div key={n.id}>
      <button
        type="button"
        onClick={() => select(n.id)}
        title={`${n.level}: ${n.name} — ${n.total_nodes} node(s)`}
        style={{
          display: 'flex', width: '100%', alignItems: 'center', gap: 6,
          padding: `3px 8px 3px ${8 + depth * 12}px`, fontSize: 12, textAlign: 'left',
          border: 'none', borderRadius: 4, cursor: 'pointer',
          background: selected === n.id ? 'var(--accent-soft, rgba(45,108,223,0.18))' : 'transparent',
          color: 'inherit',
        }}
      >
        <span style={{ fontSize: 9, textTransform: 'uppercase', opacity: 0.55, minWidth: 54 }}>{n.level}</span>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.name}</span>
        <span style={{ fontSize: 10, opacity: 0.6 }}>{n.total_nodes}</span>
      </button>
      {n.children.map(c => renderNode(c, depth + 1))}
    </div>
  )

  return (
    <div style={{ borderTop: '1px solid var(--border, #2a2a2a)', marginTop: 8, paddingTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px', gap: 6 }}>
        <button type="button" className="btn btn-ghost" style={{ fontSize: 11, padding: '2px 4px' }}
          onClick={() => setOpen(o => !o)}>
          {open ? '▾' : '▸'} Plant hierarchy
        </button>
        <span style={{ flex: 1 }} />
        {open && (
          <button type="button" className="btn btn-ghost" style={{ fontSize: 11, padding: '2px 6px' }}
            onClick={() => setAdding(a => !a)} title="Create a system and subsystem">
            {adding ? '✕' : '+'}
          </button>
        )}
      </div>

      {open && adding && (
        <div style={{ display: 'grid', gap: 4, padding: '6px 8px' }}>
          {(['area', 'system', 'subsystem'] as const).map(field => (
            <input key={field} className="input" style={{ fontSize: 12, padding: '3px 6px' }}
              placeholder={field === 'area' ? 'Area (optional)' : field[0].toUpperCase() + field.slice(1)}
              value={form[field]}
              onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))} />
          ))}
          <button type="button" className="btn" style={{ fontSize: 11 }} onClick={create}>Create subsystem</button>
        </div>
      )}

      {open && error && <div style={{ color: 'var(--danger, #e5484d)', fontSize: 11, padding: '4px 8px' }}>{error}</div>}

      {open && (
        <div style={{ maxHeight: 260, overflowY: 'auto', padding: '4px 0' }}>
          {empty ? (
            <div style={{ fontSize: 11, opacity: 0.6, padding: '4px 10px', lineHeight: 1.5 }}>
              No systems yet. Create one here, or ask the Describe agent to group this drawing by area.
            </div>
          ) : (
            tree!.roots.map(r => renderNode(r, 0))
          )}
          {tree && tree.unassigned_nodes > 0 && (
            <div style={{ fontSize: 10, opacity: 0.55, padding: '4px 10px' }}>
              {tree.unassigned_nodes} node(s) not assigned to any group
            </div>
          )}
        </div>
      )}
    </div>
  )
}

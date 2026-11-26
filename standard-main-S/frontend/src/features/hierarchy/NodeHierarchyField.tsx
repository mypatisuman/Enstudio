// Shows which system / subsystem a canvas node belongs to and lets the engineer
// move it. The Canvas side panel keys this component by node id, so its state
// starts fresh for every node; state is only set from promise callbacks, and a
// late response for a node the user already left is discarded.

import { useEffect, useState } from 'react'
import * as hierarchyService from '../../services/hierarchy'
import type { HierarchyNode } from '../../services/hierarchy'
import { emitGraphChanged } from '../../shared/graphEvents'

interface Option { id: number; path: string }

function flatten(nodes: HierarchyNode[], prefix: string[] = [], out: Option[] = []): Option[] {
  for (const n of nodes) {
    const path = [...prefix, n.name]
    out.push({ id: n.id, path: path.join(' › ') })
    flatten(n.children, path, out)
  }
  return out
}

export function NodeHierarchyField({ projectId, nodeId }: { projectId: string; nodeId: string }) {
  const [options, setOptions] = useState<Option[] | null>(null)
  const [current, setCurrent] = useState<number | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([hierarchyService.getHierarchy(projectId), hierarchyService.getNodeHierarchy(projectId)])
      .then(([tree, assignment]) => {
        if (cancelled) return
        setOptions(flatten(tree.roots))
        setCurrent(assignment[nodeId] ?? null)
      })
      .catch(e => { if (!cancelled) setError(typeof e === 'string' ? e : 'Could not load the plant hierarchy') })
    return () => { cancelled = true }
  }, [projectId, nodeId])

  const change = (value: string) => {
    const next = value === '' ? null : Number(value)
    hierarchyService.assignNodeHierarchy(projectId, nodeId, next)
      .then(() => { setCurrent(next); setError(''); emitGraphChanged(projectId) })
      .catch(e => setError(typeof e === 'string' ? e : 'Could not change the assignment'))
  }

  const labelStyle = { fontSize: 10, fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 2 }
  return (
    <div>
      <div style={labelStyle}>System / subsystem</div>
      {options === null && !error && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading…</div>}
      {options !== null && options.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No systems defined yet</div>
      )}
      {options !== null && options.length > 0 && (
        <select
          value={current ?? ''}
          onChange={e => change(e.target.value)}
          style={{ width: '100%', fontSize: 12, padding: '3px 4px', background: 'var(--bg-primary)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 4 }}
        >
          <option value="">Unassigned</option>
          {options.map(o => <option key={o.id} value={o.id}>{o.path}</option>)}
        </select>
      )}
      {error && <div style={{ fontSize: 11, color: '#f87171', marginTop: 2 }}>{error}</div>}
    </div>
  )
}

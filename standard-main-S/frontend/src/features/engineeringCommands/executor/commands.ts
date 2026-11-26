import type { ProjectContext } from '../../copilot/context/projectContext'
import type { Plan } from '../types'
import {
  updateNodeByTag, updateNodePosition, deleteNodeByTag,
  insertEdgeById, deleteEdgeById, batchInsertNodes,
} from '../../../services/graph'
import { addConnection } from '../../../services/review'
import { pickFreeSpot, parseDirection } from '../../../domain/layout/placement'

// Every supported command as a pure plan builder. Builders NEVER mutate — they
// return a `simulate` (for the validation preview) and an `apply` (the real
// mutation, returning its own inverse for Undo). This is the only place edit
// logic lives; the Copilot never edits directly.

export type CommandRequest =
  | { kind: 'rename'; tag: string; newTag: string }
  | { kind: 'rename-bulk'; fromPrefix: string; toPrefix: string }
  | { kind: 'move'; tag: string; anchorTag?: string; dir?: string }
  | { kind: 'delete-node'; tags: string[] }
  | { kind: 'delete-edge'; source: string; target: string }
  | { kind: 'disconnect'; tag: string }
  | { kind: 'delete-unused' }
  | { kind: 'create-connection'; source: string; target: string; connType: string }
  | { kind: 'connect-instrument'; instrument: string; equipment: string }
  | { kind: 'duplicate'; tag: string }
  | { kind: 'align'; tags: string[]; axis: 'v' | 'h' }
  | { kind: 'distribute'; tags: string[]; axis: 'h' | 'v' }
  | { kind: 'auto-layout'; tags: string[] }

const alphaPrefix = (tag: string) => (/^[A-Za-z]+/.exec(tag.replace(/[\s\-_]/g, '')) ?? [''])[0].toUpperCase()

export function buildPlan(req: CommandRequest, ctx: ProjectContext): Plan {
  const pid = ctx.projectId
  const byLabel = new Map(ctx.nodes.map(n => [n.label, n]))
  const labelById = new Map(ctx.nodes.map(n => [n.id, n.label]))
  const idByLabel = new Map(ctx.nodes.map(n => [n.label, n.id]))
  const find = (tag: string) => ctx.nodes.find(n => n.label.toLowerCase() === tag.toLowerCase())

  switch (req.kind) {
    case 'rename': {
      const node = find(req.tag)
      if (!node) throw new Error(`No object tagged "${req.tag}".`)
      const from = node.label, to = req.newTag.trim()
      if (!to) throw new Error('New tag is empty.')
      const warnings = byLabel.has(to) ? [`Tag "${to}" already exists — this will create a duplicate.`] : []
      return {
        title: `Rename ${from} → ${to}`,
        affected: [{ tag: from, change: `→ ${to}` }],
        warnings, destructive: true,
        simulate: s => { const n = s.nodes.find(x => x.label === from); if (n) n.label = to; return s },
        apply: async () => { await updateNodeByTag(pid, from, to); return async () => { await updateNodeByTag(pid, to, from) } },
      }
    }

    case 'rename-bulk': {
      const from = req.fromPrefix.toUpperCase(), to = req.toPrefix.toUpperCase()
      const targets = ctx.nodes.filter(n => n.label.trim() && alphaPrefix(n.label) === from)
      if (!targets.length) throw new Error(`No tags starting with "${from}".`)
      const pairs = targets.map(n => ({ from: n.label, to: n.label.replace(new RegExp(`^${from}`, 'i'), to) }))
      const collisions = pairs.filter(p => byLabel.has(p.to) || pairs.filter(q => q.to === p.to).length > 1)
      return {
        title: `Rename ${pairs.length} tag(s): ${from} → ${to}`,
        affected: pairs.map(p => ({ tag: p.from, change: `→ ${p.to}` })),
        warnings: collisions.length ? [`${collisions.length} rename(s) would collide with an existing/duplicate tag.`] : [],
        destructive: true,
        simulate: s => { for (const p of pairs) { const n = s.nodes.find(x => x.label === p.from); if (n) n.label = p.to } return s },
        apply: async () => {
          for (const p of pairs) await updateNodeByTag(pid, p.from, p.to)
          return async () => { for (const p of pairs) await updateNodeByTag(pid, p.to, p.from) }
        },
      }
    }

    case 'move': {
      const node = find(req.tag)
      if (!node) throw new Error(`No object tagged "${req.tag}".`)
      const anchor = req.anchorTag ? find(req.anchorTag) : null
      if (!anchor) throw new Error(`Move needs a reference object, e.g. "move ${req.tag} near <tag>".`)
      const occupied = ctx.nodes.filter(n => n.id !== node.id).map(n => ({ x: n.x, y: n.y }))
      const spot = pickFreeSpot({ x: anchor.x, y: anchor.y }, occupied, req.dir ? parseDirection(req.dir) : null)
      const oldX = node.x, oldY = node.y, id = node.id
      return {
        title: `Move ${node.label} near ${anchor.label}`,
        affected: [{ tag: node.label, change: `near ${anchor.label}` }],
        warnings: [], destructive: false,
        simulate: s => s,   // position doesn't affect validation
        apply: async () => { await updateNodePosition(pid, id, spot.x, spot.y); return async () => { await updateNodePosition(pid, id, oldX, oldY) } },
      }
    }

    case 'delete-node':
    case 'delete-unused': {
      const tags = req.kind === 'delete-unused'
        ? ctx.issues.filter(i => i.ruleId === 'floating-symbols').map(i => i.tag).filter((t): t is string => !!t)
        : req.tags
      const nodes = tags.map(t => byLabel.get(t) ?? find(t)).filter((n): n is NonNullable<typeof n> => !!n)
      if (!nodes.length) throw new Error(req.kind === 'delete-unused' ? 'No unused (floating) symbols to delete.' : 'None of those tags exist.')
      // Capture each node + its restorable incident edges (both endpoints have a
      // tag) so Undo can rebuild it — addConnection is tag-based, so it survives
      // the new node id the re-insert assigns (id-instability workaround).
      const removed = nodes.map(node => ({
        node,
        incident: ctx.edges
          .filter(e => e.source === node.id || e.target === node.id)
          .map(e => ({ src: labelById.get(e.source), tgt: labelById.get(e.target), kind: e.kind || 'stream' }))
          .filter(x => x.src && x.tgt),
      }))
      const ids = new Set(nodes.map(n => n.id))
      return {
        title: req.kind === 'delete-unused' ? `Delete ${nodes.length} unused symbol(s)` : `Delete ${nodes.map(n => n.label).join(', ')}`,
        affected: nodes.map(n => ({ tag: n.label, change: 'delete (with connections)' })),
        warnings: ['Deletes the symbol(s) and every connection to them.'],
        destructive: true,
        simulate: s => {
          s.nodes = s.nodes.filter(n => !nodes.some(d => d.label === n.label))
          s.edges = s.edges.filter(e => !ids.has(e.source) && !ids.has(e.target))
          return s
        },
        apply: async () => {
          for (const { node } of removed) await deleteNodeByTag(pid, node.label)
          return async () => {
            for (const { node, incident } of removed) {
              await batchInsertNodes(pid, JSON.stringify([{
                tag: node.label, kind: node.kind_detail || node.kind, description: '', area: node.area,
                x: node.x, y: node.y, drawing: node.drawing,
              }]))
              for (const e of incident) await addConnection(pid, e.src!, e.tgt!, e.kind).catch(() => {})
            }
          }
        },
      }
    }

    case 'delete-edge': {
      const s = idByLabel.get(req.source), t = idByLabel.get(req.target)
      if (!s || !t) throw new Error('Both endpoints must exist to delete a connection.')
      const edge = ctx.edges.find(e => e.source === s && e.target === t)
      if (!edge) throw new Error(`No connection ${req.source} → ${req.target}.`)
      const kind = edge.kind || 'stream'
      return {
        title: `Delete connection ${req.source} → ${req.target}`,
        affected: [{ tag: `${req.source}→${req.target}`, change: 'remove connection' }],
        warnings: [], destructive: true,
        simulate: st => { st.edges = st.edges.filter(e => !(e.source === s && e.target === t)); return st },
        apply: async () => { await deleteEdgeById(pid, s, t); return async () => { await insertEdgeById(pid, s, t, kind) } },
      }
    }

    case 'disconnect': {
      const node = find(req.tag)
      if (!node) throw new Error(`No object tagged "${req.tag}".`)
      const incident = ctx.edges.filter(e => e.source === node.id || e.target === node.id)
      if (!incident.length) throw new Error(`"${node.label}" has no connections.`)
      const saved = incident.map(e => ({ s: e.source, t: e.target, kind: e.kind || 'stream' }))
      const id = node.id
      return {
        title: `Disconnect ${node.label} (${incident.length} connection(s))`,
        affected: [{ tag: node.label, change: `remove ${incident.length} connection(s)` }],
        warnings: [`"${node.label}" will become disconnected.`], destructive: true,
        simulate: st => { st.edges = st.edges.filter(e => e.source !== id && e.target !== id); return st },
        apply: async () => {
          for (const e of saved) await deleteEdgeById(pid, e.s, e.t)
          return async () => { for (const e of saved) await insertEdgeById(pid, e.s, e.t, e.kind) }
        },
      }
    }

    case 'create-connection':
    case 'connect-instrument': {
      const srcTag = req.kind === 'create-connection' ? req.source : req.instrument
      const tgtTag = req.kind === 'create-connection' ? req.target : req.equipment
      const connType = req.kind === 'create-connection' ? (req.connType || 'stream') : 'signal'
      const src = find(srcTag), tgt = find(tgtTag)
      if (!src || !tgt) throw new Error(`Both ${srcTag} and ${tgtTag} must exist.`)
      const sId = src.id, tId = tgt.id
      const dup = ctx.edges.some(e => e.source === sId && e.target === tId)
      return {
        title: `Connect ${src.label} → ${tgt.label}`,
        affected: [{ tag: `${src.label}→${tgt.label}`, change: `${connType} connection` }],
        warnings: dup ? ['This connection already exists — it would be duplicated.'] : [],
        destructive: true,
        simulate: st => { st.edges = [...st.edges, { source: sId, target: tId, kind: connType, waypoints: null, bend_x: null, bend_y: null }]; return st },
        apply: async () => { await addConnection(pid, src.label, tgt.label, connType); return async () => { await deleteEdgeById(pid, sId, tId) } },
      }
    }

    case 'duplicate': {
      const node = find(req.tag)
      if (!node) throw new Error(`No object tagged "${req.tag}".`)
      const existing = new Set(ctx.nodes.map(n => n.label))
      let newTag = `${node.label}-COPY`, i = 2
      while (existing.has(newTag)) newTag = `${node.label}-COPY${i++}`
      const occupied = ctx.nodes.map(n => ({ x: n.x, y: n.y }))
      const spot = pickFreeSpot({ x: node.x, y: node.y }, occupied)
      return {
        title: `Duplicate ${node.label} → ${newTag}`,
        affected: [{ tag: node.label, change: `copy → ${newTag}` }],
        warnings: [`${newTag} starts with no connections (a floating symbol).`],
        destructive: false,
        simulate: st => { st.nodes = [...st.nodes, { ...node, id: `sim_${newTag}`, label: newTag, x: spot.x, y: spot.y }]; return st },
        apply: async () => {
          await batchInsertNodes(pid, JSON.stringify([{
            tag: newTag, kind: node.kind_detail || node.kind, description: '', area: node.area, x: spot.x, y: spot.y, drawing: node.drawing,
          }]))
          return async () => { await deleteNodeByTag(pid, newTag) }
        },
      }
    }

    case 'align':
    case 'distribute':
    case 'auto-layout': {
      const nodes = req.kind === 'auto-layout'
        ? req.tags.map(t => byLabel.get(t)).filter((n): n is NonNullable<typeof n> => !!n)
        : req.tags.map(t => byLabel.get(t)).filter((n): n is NonNullable<typeof n> => !!n)
      if (nodes.length < 2) throw new Error('Select at least two objects for a layout operation.')
      const saved = nodes.map(n => ({ id: n.id, x: n.x, y: n.y }))
      const targets = layoutPositions(req, nodes.map(n => ({ id: n.id, x: n.x, y: n.y })))
      const verb = req.kind === 'align' ? 'Align' : req.kind === 'distribute' ? 'Distribute' : 'Auto-layout'
      return {
        title: `${verb} ${nodes.length} object(s)`,
        affected: nodes.map(n => ({ tag: n.label, change: 'reposition' })),
        warnings: [], destructive: false,
        simulate: s => s,   // positions only
        apply: async () => {
          for (const p of targets) await updateNodePosition(pid, p.id, p.x, p.y)
          return async () => { for (const p of saved) await updateNodePosition(pid, p.id, p.x, p.y) }
        },
      }
    }
  }
}

// Geometry for align / distribute / auto-layout, in the normalized 0–1 space.
function layoutPositions(
  req: Extract<CommandRequest, { kind: 'align' | 'distribute' | 'auto-layout' }>,
  pts: { id: string; x: number; y: number }[],
): { id: string; x: number; y: number }[] {
  if (req.kind === 'align') {
    if (req.axis === 'v') { const x = Math.min(...pts.map(p => p.x)); return pts.map(p => ({ ...p, x })) }
    const y = Math.min(...pts.map(p => p.y)); return pts.map(p => ({ ...p, y }))
  }
  if (req.kind === 'distribute') {
    const key = req.axis === 'h' ? 'x' : 'y'
    const sorted = [...pts].sort((a, b) => a[key] - b[key])
    const lo = sorted[0][key], hi = sorted[sorted.length - 1][key]
    const step = (hi - lo) / (sorted.length - 1)
    return sorted.map((p, i) => ({ ...p, [key]: lo + step * i }))
  }
  // auto-layout: simple grid around the centroid — ponytail: a plain grid, not
  // dagre; wire in the Canvas's dagre layout if hierarchical output is needed.
  const cols = Math.ceil(Math.sqrt(pts.length))
  const gap = 0.07
  const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length
  const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length
  const x0 = cx - (gap * (cols - 1)) / 2
  const y0 = cy - (gap * (Math.ceil(pts.length / cols) - 1)) / 2
  return pts.map((p, i) => ({
    id: p.id,
    x: Math.min(0.98, Math.max(0.02, x0 + gap * (i % cols))),
    y: Math.min(0.98, Math.max(0.02, y0 + gap * Math.floor(i / cols))),
  }))
}

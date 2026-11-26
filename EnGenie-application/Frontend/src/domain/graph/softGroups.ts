// Soft-tag grouping — collapses alarm/switch "soft tags" (AL-101, PAH-101,
// etc.) into their parent instrument so the canvas can render them as a
// "+N alarms" badge instead of separate boxes. Pure graph-node-array logic,
// moved out of CanvasScreen.tsx unchanged.

import { isInstrument } from '../isa/instrument'

// The minimal node shape this module needs — CanvasScreen's own GraphNode
// (and any other node type with these fields) satisfies this structurally.
export interface SoftGroupNode {
  id: string
  label: string
  kind: string
  drawing: string
}

const SOFT_PREFIXES = new Set([
  'AL', 'AH', 'ALL', 'AHH', 'AHLL',
  'PAL', 'PAH', 'PALL', 'PAHH',
  'TAL', 'TAH', 'TALL', 'TAHH',
  'LAL', 'LAH', 'LALL', 'LAHH',
  'FAL', 'FAH', 'FALL', 'FAHH',
  'PSL', 'PSH', 'PSLL', 'PSHH',
  'TSL', 'TSH', 'TSLL', 'TSHH',
  'LSL', 'LSH', 'LSLL', 'LSHH',
  'FSL', 'FSH', 'FSLL', 'FSHH',
])

export function isSoftTag(label: string, kind: string): boolean {
  if (kind === 'alarm') return true
  if (kind === 'switch') return true
  const up = label.toUpperCase()
  for (const pfx of SOFT_PREFIXES) {
    if (up.startsWith(pfx)) {
      const rest = up.slice(pfx.length)
      if (rest === '' || /^[-_\d]/.test(rest)) return true
    }
  }
  return false
}

function extractBase(label: string): string {
  const m = label.match(/(\d+)/)
  return m ? m[1] : ''
}

function bestParent<T extends SoftGroupNode>(softLabel: string, candidates: T[]): T | undefined {
  if (!candidates.length) return undefined
  if (candidates.length === 1) return candidates[0]
  const instrs = candidates.filter(n => isInstrument(n.kind))
  const pool = instrs.length ? instrs : candidates
  const fl = softLabel.match(/^([A-Z])/i)?.[1]?.toUpperCase() ?? ''
  if (fl) {
    const match = pool.filter(n => n.label.toUpperCase().startsWith(fl))
    if (match.length) return match[0]
  }
  return pool[0]
}

export function buildSoftGroups<T extends SoftGroupNode>(nodes: T[]): {
  parentToChildren: Map<string, T[]>
  unmatchedSoftIds: Set<string>
} {
  const primaries = nodes.filter(n => !isSoftTag(n.label, n.kind))
  const softs = nodes.filter(n => isSoftTag(n.label, n.kind))

  const idx = new Map<string, T[]>()
  primaries.forEach(n => {
    const base = extractBase(n.label)
    if (!base) return
    const key = `${n.drawing}|${base}`
    if (!idx.has(key)) idx.set(key, [])
    idx.get(key)!.push(n)
  })

  const parentToChildren = new Map<string, T[]>()
  const unmatchedSoftIds = new Set<string>()

  softs.forEach(soft => {
    const base = extractBase(soft.label)
    if (!base) { unmatchedSoftIds.add(soft.id); return }
    let candidates = idx.get(`${soft.drawing}|${base}`) ?? []
    if (!candidates.length) {
      candidates = []
      idx.forEach((v, k) => { if (k.endsWith(`|${base}`)) candidates.push(...v) })
    }
    const parent = bestParent(soft.label, candidates)
    if (!parent) { unmatchedSoftIds.add(soft.id); return }
    if (!parentToChildren.has(parent.id)) parentToChildren.set(parent.id, [])
    parentToChildren.get(parent.id)!.push(soft)
  })

  return { parentToChildren, unmatchedSoftIds }
}

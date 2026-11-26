// DescribeScreen's auto-placement for newly added nodes — a third, independent
// placement algorithm from processLayout.ts/extractedLayout.ts (confirmed
// during Phase 1 analysis); do not merge with those.
//
// Places newly added nodes right next to whatever existing (or already-placed
// new) node they connect to — checking below/above/right/left/diagonals for
// whichever direction is actually clear of other symbols, instead of always
// offsetting to a fixed side regardless of what's already sitting there.
//
// Stored x/y are normalized 0–1 fractions of the drawing sheet (see
// extractedLayout.ts), NOT pixels — offsets here must stay in that same
// [0,1] space and get clamped, or a single stray coordinate (e.g. 220 instead
// of 0.22) makes React Flow's fit-to-view zoom out until the whole canvas
// reads as blank.
// Matched to this app's own extracted spacing (e.g. the ~0.058 gap between an
// existing equipment/instrument pair on a typical sheet) rather than a guess —
// smaller fractions here read as visually identical since the sheet is wide.
import { clamp01 } from '../geometry/clamp'

const NEW_NODE_OFFSET = 0.055
const MIN_CLEARANCE = 0.03

// Preferred directions, closest-fit first: straight right, below, above, left,
// then the four diagonals. Left-to-right is standard P&ID flow.
const PLACEMENT_DIRECTIONS = [
  { dx: 1, dy: 0 }, { dx: 0, dy: 1 }, { dx: 0, dy: -1 }, { dx: -1, dy: 0 },
  { dx: 1, dy: 1 }, { dx: -1, dy: 1 }, { dx: 1, dy: -1 }, { dx: -1, dy: -1 },
]

export function nearestDist(p: { x: number; y: number }, points: { x: number; y: number }[]): number {
  let best = Infinity
  for (const q of points) {
    const d = Math.hypot(p.x - q.x, p.y - q.y)
    if (d < best) best = d
  }
  return best
}

// Reads the user's own instruction for an explicit side ("left", "above the
// heat exchanger", etc.) so that wins over the automatic free-space scan
// below. Returns null when no directional word is present.
export function parseDirection(text: string): { dx: number; dy: number } | null {
  if (text.length > 120) return null // Prevent false positives on long descriptive prompts
  const t = text.toLowerCase()
  const left  = /\bleft\b/.test(t)
  const right = /\bright\b/.test(t)
  const up    = /\b(above|top|over|upper)\b/.test(t)
  const down  = /\b(below|under|beneath|bottom|lower)\b/.test(t)
  let dx = 0, dy = 0
  if (left)  dx = -1
  else if (right) dx = 1
  if (up)    dy = -1
  else if (down)  dy = 1
  return (dx || dy) ? { dx, dy } : null
}

// Tries each direction around the anchor and picks the first one clear of
// every other known node; if none are fully clear, picks whichever candidate
// has the most breathing room. When `preferredDir` is given (the user asked
// for a specific side), that direction is tried first — and if it's a little
// crowded, nearby positions on the SAME side are tried before ever falling
// back to a different side, so an explicit "left" request never silently
// becomes "below" just because below happened to be emptier.
export function pickFreeSpot(
  anchor: { x: number; y: number }, occupied: { x: number; y: number }[],
  preferredDir?: { dx: number; dy: number } | null,
): { x: number; y: number } {
  if (preferredDir) {
    const perp = { dx: -preferredDir.dy, dy: preferredDir.dx }
    for (const j of [0, 1, -1, 2, -2]) {
      const cand = {
        x: clamp01(anchor.x + preferredDir.dx * NEW_NODE_OFFSET + perp.dx * j * NEW_NODE_OFFSET * 0.6),
        y: clamp01(anchor.y + preferredDir.dy * NEW_NODE_OFFSET + perp.dy * j * NEW_NODE_OFFSET * 0.6),
      }
      if (nearestDist(cand, occupied) >= MIN_CLEARANCE) return cand
    }
    // Honor the requested side even if it's tight — the user asked for it explicitly.
    return { x: clamp01(anchor.x + preferredDir.dx * NEW_NODE_OFFSET), y: clamp01(anchor.y + preferredDir.dy * NEW_NODE_OFFSET) }
  }

  let fallback = { x: clamp01(anchor.x + NEW_NODE_OFFSET), y: anchor.y }
  let fallbackScore = -Infinity
  for (const d of PLACEMENT_DIRECTIONS) {
    const cand = { x: clamp01(anchor.x + d.dx * NEW_NODE_OFFSET), y: clamp01(anchor.y + d.dy * NEW_NODE_OFFSET) }
    const score = nearestDist(cand, occupied)
    if (score >= MIN_CLEARANCE) return cand
    if (score > fallbackScore) { fallbackScore = score; fallback = cand }
  }
  return fallback
}

interface PlacementNode { label: string; x: number; y: number; drawing: string }
interface PlacementEdge { from_tag: string; to_tag: string }

export function placeNewNodes(
  existing: PlacementNode[], addNodes: { tag: string }[], addEdges: PlacementEdge[],
  preferredDir?: { dx: number; dy: number } | null,
  extraTags: string[] = [],   // junction ids — placed the same way, but only kept if an edge actually anchors them
): Map<string, { x: number; y: number; drawing?: string }> {
  const pos = new Map<string, { x: number; y: number; drawing?: string }>()
  existing.forEach(n => { if (n.label) pos.set(n.label, { x: n.x, y: n.y, drawing: n.drawing }) })

  const newTags = new Set([...addNodes.map(n => n.tag), ...extraTags])
  const occupied = () => Array.from(pos.values()).map(p => ({ x: p.x, y: p.y }))

  let changed = true
  let guard = 0
  let fallbackIndex = 0
  while (guard++ < 20) {
    changed = false
    for (const e of addEdges) {
      const a = pos.get(e.from_tag)
      const b = pos.get(e.to_tag)
      if (a && newTags.has(e.to_tag) && !pos.has(e.to_tag)) {
        const spot = pickFreeSpot(a, occupied(), preferredDir)
        pos.set(e.to_tag, { ...spot, drawing: a.drawing })
        changed = true
      } else if (b && newTags.has(e.from_tag) && !pos.has(e.from_tag)) {
        // "anchor" here is still the existing node the user named (e.g. the
        // heat exchanger) regardless of which side of the edge it's on —
        // the preferred direction is relative to that named anchor, so it
        // is NOT flipped just because this branch anchors off "to" instead
        // of "from".
        const spot = pickFreeSpot(b, occupied(), preferredDir)
        pos.set(e.from_tag, { ...spot, drawing: b.drawing })
        changed = true
      }
    }

    // If no edges were routed in this pass (e.g. empty canvas or disjoint graph),
    // seed one unplaced node to start a new cluster and continue routing from it.
    if (!changed) {
      const unplaced = addNodes.find(n => !pos.has(n.tag))
      if (!unplaced) break // All nodes placed

      pos.set(unplaced.tag, { x: clamp01(0.1 + fallbackIndex * 0.08), y: 0.3 })
      fallbackIndex++
      changed = true
    }
  }

  // Fallback for any remaining unplaced extraTags/junctions with no edges
  for (const n of addNodes) {
    if (!pos.has(n.tag)) {
      pos.set(n.tag, { x: clamp01(0.1 + fallbackIndex * 0.08), y: 0.3 })
      fallbackIndex++
    }
  }
  return pos
}

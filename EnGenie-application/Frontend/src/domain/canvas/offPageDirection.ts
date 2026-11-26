import { isOffPage } from '../isa/instrument'

// Role is taken from the label first (reliable: "TO …", VENT, DRAIN, RECYCLE
// are outlets; FROM/SUPPLY/FEED are inlets), then from edge direction.
const OUTLET_RE = /\b(TO|VENT|DRAIN|RECYCLE|FLARE|SAMPLE|OUTLET|RELIEF|RETURN)\b/i
const INLET_RE = /\b(FROM|INLET|SUPPLY|FEED|EFFLUENT)\b/i

interface OffPageCandidate {
  id: string
  type?: string | null
  kind: string
  label: string
  category?: string
}
interface OffPageEdge { source: string; target: string }

// Decides which side (left/right) an off-page connector pentagon points,
// oriented against the rendered x-position of whatever node it connects to —
// moved out of CanvasScreen's rfNodes useMemo (previously an inline block,
// same logic verbatim).
export function computeOffPageDirections(
  nodes: OffPageCandidate[],
  edges: OffPageEdge[],
  xById: Map<string, number | undefined>,
): Map<string, 'left' | 'right'> {
  // Tally edge roles per node (source vs target count)
  const srcCount = new Map<string, number>()
  const tgtCount = new Map<string, number>()
  for (const e of edges) {
    srcCount.set(e.source, (srcCount.get(e.source) ?? 0) + 1)
    tgtCount.set(e.target, (tgtCount.get(e.target) ?? 0) + 1)
  }
  const offDirById = new Map<string, 'left' | 'right'>()
  for (const n of nodes) {
    if (!isOffPage(n.type ?? n.kind, n.label, n.category)) continue

    // Neighbour x (first connected node)
    let ox: number | undefined
    for (const e of edges) {
      const otherId = e.source === n.id ? e.target : e.target === n.id ? e.source : null
      if (otherId != null) { ox = xById.get(otherId); if (ox != null) break }
    }

    // Determine inlet vs outlet. The detector's raw `type` ("Inlet"/"Outlet")
    // is authoritative — honour it first. Only fall back to label keywords and
    // edge direction when type is absent (older extractions).
    const lbl = n.label ?? ''
    const t = (n.type ?? '').toLowerCase()
    let isOutlet: boolean
    if (t === 'outlet') isOutlet = true    // type says outlet → ◄
    else if (t === 'inlet') isOutlet = false   // type says inlet  → ►
    else if (OUTLET_RE.test(lbl)) isOutlet = true    // label says return/vent
    else if (INLET_RE.test(lbl)) isOutlet = false   // label says supply/inlet
    else isOutlet = (tgtCount.get(n.id) ?? 0) >= (srcCount.get(n.id) ?? 0)  // sink → outlet

    // The pentagon points ALONG the flow relative to the connected process node:
    //   - inlet  (feed IN)  → points TOWARD the process node
    //   - outlet (stream OUT) → points AWAY from it (off the page)
    // Pointing purely by type (all outlets left) is wrong: when the process sits
    // to a connector's left, a left arrow points back INTO the process and reads
    // as an inlet. Orient against the neighbour's rendered position instead.
    const nx = xById.get(n.id)
    let dir: 'left' | 'right'
    if (ox != null && nx != null && ox !== nx) {
      const neighbourOnLeft = ox < nx
      dir = isOutlet
        ? (neighbourOnLeft ? 'right' : 'left')   // away from the process
        : (neighbourOnLeft ? 'left' : 'right')  // toward the process
    } else {
      dir = isOutlet ? 'left' : 'right'          // no neighbour — type-based default
    }
    offDirById.set(n.id, dir)
  }
  return offDirById
}

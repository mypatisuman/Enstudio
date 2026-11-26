/**
 * Map Claude extraction coordinates (0–1 on the drawing sheet) to React Flow pixels.
 * (0,0) = top-left of drawing area; (1,1) = bottom-right — matches PASS1_SINGLE_PAGE prompt.
 */

// Explicit .ts extension (allowed by tsconfig's allowImportingTsExtensions) so
// the sibling test can run under plain `node`, which won't resolve extensionless.
import { clamp01 } from '../../src/domain/geometry/clamp.ts'

/** Small inset so symbols at sheet edge are not clipped */
export const EXTRACTED_MARGIN = 24

export interface ExtractedNode {
  id: string
  label: string
  kind: string
  type?: string
  x: number
  y: number
  drawing?: string          // drawing number — used to tile multi-drawing layouts
  equipment_ref?: string    // parent vendor_package/package id — used to pack children inside
  page_w?: number           // raster size this node's x/y were normalised
  page_h?: number           // against (Phase 3) — sizes the drawing's cell
}

export interface LayoutResult {
  pos: Map<string, { x: number; y: number }>
  sizes: Map<string, { w: number; h: number }>   // size overrides (vendor packages)
}

// Default sheet size in multi-drawing grid mode, used only when a drawing's
// real raster dimensions are unknown (pre-Phase-3 extractions).
const CELL_W = 2800
const CELL_H = 2000
const CELL_GAP = 120   // gap between drawing cells

// Longest side of a drawing cell, in flow pixels. Real page rasters are
// capped at 4096px by the extractor; scaling every sheet to a common longest
// side keeps a mixed A1/A4 set comparable on screen while preserving each
// sheet's own aspect ratio.
const CELL_LONG_SIDE = 2800

/**
 * Cell size for one drawing, derived from the real page raster when the
 * extraction recorded it.
 *
 * Phase 3: every drawing used to get a fixed 2800x2000 cell, so a portrait
 * sheet was squashed and a wide sheet stretched — node positions are
 * normalised against their own page, so the cell has to carry that page's
 * aspect ratio or the whole layout is skewed.
 */
export function cellSizeFor(
  nodes: { page_w?: number; page_h?: number }[],
): { w: number; h: number } {
  const withDims = nodes.find(
    n => typeof n.page_w === 'number' && typeof n.page_h === 'number' &&
         Number.isFinite(n.page_w) && Number.isFinite(n.page_h) &&
         (n.page_w as number) > 0 && (n.page_h as number) > 0,
  )
  if (!withDims) return { w: CELL_W, h: CELL_H }
  const pw = withDims.page_w as number
  const ph = withDims.page_h as number
  const scale = CELL_LONG_SIDE / Math.max(pw, ph)
  return { w: Math.round(pw * scale), h: Math.round(ph * scale) }
}

// Vendor-package packing constants
const PKG_TITLE_H = 28   // header row inside the dashed box
const PKG_PAD     = 14   // inner padding around children
const PKG_CHILD_GAP = 10

export function hasExtractedPositions(nodes: { x: number; y: number }[]): boolean {
  if (nodes.length < 2) return false
  const xs = nodes.map(n => n.x)
  const ys = nodes.map(n => n.y)
  const inUnit = nodes.every(n => n.x >= 0 && n.x <= 1.05 && n.y >= 0 && n.y <= 1.05)
  if (!inUnit) return false
  const dx = Math.max(...xs) - Math.min(...xs)
  const dy = Math.max(...ys) - Math.min(...ys)
  return dx > 0.04 && dy > 0.04
}

/**
 * Place vendor-package children in a grid inside their parent's dashed box,
 * and expand the parent box to wrap them. Mutates `pos`, returns size overrides.
 */
export function packVendorPackages(
  nodes: ExtractedNode[],
  pos: Map<string, { x: number; y: number }>,
  getSize: (n: ExtractedNode) => { w: number; h: number },
): Map<string, { w: number; h: number }> {
  const sizes = new Map<string, { w: number; h: number }>()
  const byId = new Map(nodes.map(n => [n.id, n]))

  // Group children by their parent package id
  const childrenOf = new Map<string, ExtractedNode[]>()
  for (const n of nodes) {
    const ref = n.equipment_ref
    const refKind = ref ? byId.get(ref)?.kind : undefined
    if (ref && (refKind === 'vendor_package' || refKind === 'package')) {
      const arr = childrenOf.get(ref) ?? []
      arr.push(n)
      childrenOf.set(ref, arr)
    }
  }

  // Packages nest (an instrument inside a GCV box inside a VENDOR PACKAGE), so
  // pack the DEEPEST boxes first: a parent must be sized against its child's
  // already-expanded box, not the child's default size, or it wraps too small
  // and the child spills out. Map iteration order gave whichever came first.
  const depthOf = (id: string): number => {
    let d = 0
    for (let cur = byId.get(id)?.equipment_ref; cur; cur = byId.get(cur)?.equipment_ref) {
      if (!childrenOf.has(cur)) break
      if (++d > nodes.length) break   // ponytail: cycle guard; extraction can emit a ref loop
    }
    return d
  }
  // A child package already had its own children positioned, so moving it must
  // move that whole subtree with it.
  const subtreeOf = (id: string): string[] => {
    const out: string[] = []
    const seen = new Set<string>([id])   // ponytail: same cycle guard as depthOf
    const stack = [...(childrenOf.get(id) ?? [])]
    while (stack.length) {
      const n = stack.pop()!
      if (seen.has(n.id)) continue
      seen.add(n.id)
      out.push(n.id)
      stack.push(...(childrenOf.get(n.id) ?? []))
    }
    return out
  }
  const sizeOf = (n: ExtractedNode) => sizes.get(n.id) ?? getSize(n)

  const order = [...childrenOf.keys()].sort((a, b) => depthOf(b) - depthOf(a))
  for (const pkgId of order) {
    const children = childrenOf.get(pkgId)!
    if (!children.length) continue
    const pkgPos = pos.get(pkgId)
    if (!pkgPos) continue

    // Grid dimensions
    const cols = Math.ceil(Math.sqrt(children.length))
    const rows = Math.ceil(children.length / cols)

    // Cell size = largest child + gap
    let cellW = 0, cellH = 0
    for (const c of children) {
      const s = sizeOf(c)
      cellW = Math.max(cellW, s.w)
      cellH = Math.max(cellH, s.h)
    }
    cellW += PKG_CHILD_GAP
    cellH += PKG_CHILD_GAP

    const boxW = PKG_PAD * 2 + cols * cellW
    const boxH = PKG_TITLE_H + PKG_PAD + rows * cellH

    // Anchor the box around the package's current center
    const pkgSize = sizeOf(byId.get(pkgId)!)
    const cx = pkgPos.x + pkgSize.w / 2
    const cy = pkgPos.y + pkgSize.h / 2
    const boxLeft = cx - boxW / 2
    const boxTop  = cy - boxH / 2

    pos.set(pkgId, { x: boxLeft, y: boxTop })
    sizes.set(pkgId, { w: boxW, h: boxH })

    // Lay children in the grid
    children.forEach((c, i) => {
      const col = i % cols
      const row = Math.floor(i / cols)
      const s = sizeOf(c)
      const cellLeft = boxLeft + PKG_PAD + col * cellW
      const cellTop  = boxTop + PKG_TITLE_H + row * cellH
      // center child within its cell
      const to = {
        x: cellLeft + (cellW - PKG_CHILD_GAP - s.w) / 2,
        y: cellTop + (cellH - PKG_CHILD_GAP - s.h) / 2,
      }
      const from = pos.get(c.id)
      pos.set(c.id, to)
      // If c is itself a package, its contents were already laid out around its
      // old centre — carry them along by the same delta.
      if (from && childrenOf.has(c.id)) {
        const dx = to.x - from.x, dy = to.y - from.y
        for (const id of subtreeOf(c.id)) {
          const p = pos.get(id)
          if (p) pos.set(id, { x: p.x + dx, y: p.y + dy })
        }
      }
    })
  }

  return sizes
}

interface AlignGroups {
  H: Map<string, string>   // node id → group root id — members share a Y (horizontal run)
  V: Map<string, string>   // node id → group root id — members share an X (vertical run)
}

function ufFind(p: Map<string, string>, a: string): string {
  let r = a; while (p.get(r) !== r) r = p.get(r)!
  while (p.get(a) !== r) { const nx = p.get(a)!; p.set(a, r); a = nx }
  return r
}
function ufUnion(p: Map<string, string>, a: string, b: string) { p.set(ufFind(p, a), ufFind(p, b)) }

/**
 * Classify which connected symbols are ALMOST colinear (a pipe run — valve →
 * regulator → valve etc.) from their RAW extracted positions, before any
 * collision push has a chance to distort the geometry. P&ID source lines are
 * orthogonal, so a small off-axis gap at extraction time reliably means
 * "meant to be a straight run"; a large one means a real bend.
 * ponytail: threshold=36px catches typical valve-run jitter; raise it if runs
 * still read jagged, lower it if unrelated symbols get yanked together.
 */
function computeAlignGroups(
  nodes: ExtractedNode[],
  edges: { source: string; target: string }[],
  pos: Map<string, { x: number; y: number }>,
  getSize: (n: ExtractedNode) => { w: number; h: number },
  threshold = 36,
): AlignGroups {
  const size = new Map(nodes.map(n => [n.id, getSize(n)]))
  const cx = (id: string) => { const p = pos.get(id), s = size.get(id); return p && s ? p.x + s.w / 2 : null }
  const cy = (id: string) => { const p = pos.get(id), s = size.get(id); return p && s ? p.y + s.h / 2 : null }

  // A tee lands in both H and V — no conflict, since each set only touches one axis.
  const mk = () => { const p = new Map<string, string>(); nodes.forEach(n => p.set(n.id, n.id)); return p }
  const H = mk(), V = mk()

  for (const e of edges) {
    const ax = cx(e.source), ay = cy(e.source), bx = cx(e.target), by = cy(e.target)
    if (ax == null || ay == null || bx == null || by == null) continue
    const dx = Math.abs(bx - ax), dy = Math.abs(by - ay)
    if (dy <= threshold && dy <= dx) ufUnion(H, e.source, e.target)       // near-horizontal pipe
    else if (dx <= threshold && dx < dy) ufUnion(V, e.source, e.target)   // near-vertical pipe
  }
  return { H, V }
}

/** Snap each alignment group's members onto their shared centerline. */
function snapAlignGroups(
  nodes: ExtractedNode[],
  groups: AlignGroups,
  pos: Map<string, { x: number; y: number }>,
  getSize: (n: ExtractedNode) => { w: number; h: number },
): void {
  const size = new Map(nodes.map(n => [n.id, getSize(n)]))
  const cx = (id: string) => { const p = pos.get(id), s = size.get(id); return p && s ? p.x + s.w / 2 : null }
  const cy = (id: string) => { const p = pos.get(id), s = size.get(id); return p && s ? p.y + s.h / 2 : null }

  const snap = (p: Map<string, string>, axis: 'x' | 'y') => {
    const byRoot = new Map<string, string[]>()
    nodes.forEach(n => { const r = ufFind(p, n.id); const arr = byRoot.get(r) ?? []; arr.push(n.id); byRoot.set(r, arr) })
    for (const ids of byRoot.values()) {
      if (ids.length < 2) continue
      const c = (id: string) => (axis === 'y' ? cy(id) : cx(id)) ?? 0
      const avg = ids.reduce((s, id) => s + c(id), 0) / ids.length
      for (const id of ids) {
        const pp = pos.get(id), s = size.get(id)
        if (!pp || !s) continue
        pos.set(id, axis === 'y' ? { x: pp.x, y: avg - s.h / 2 } : { x: avg - s.w / 2, y: pp.y })
      }
    }
  }
  snap(groups.H, 'y')
  snap(groups.V, 'x')
}

export function extractedLayout(
  nodes: ExtractedNode[],
  getSize: (n: ExtractedNode) => { w: number; h: number },
  canvasW: number,
  canvasH: number,
  edges: { source: string; target: string }[] = [],
): LayoutResult {
  const pos = new Map<string, { x: number; y: number }>()

  // Group nodes by drawing when multiple drawings are present
  const drawingIds = Array.from(new Set(nodes.map(n => n.drawing ?? 'unknown'))).sort()
  const isMulti = drawingIds.length > 1

  if (isMulti) {
    // Each drawing gets a cell sized to its OWN page aspect ratio. Rows are
    // laid out on the tallest cell in that row and columns on the widest in
    // that column, so a portrait sheet next to a landscape one never overlaps
    // it — which a single fixed cell size could not guarantee once the cells
    // stopped being identical.
    const COLS = Math.min(drawingIds.length, Math.ceil(Math.sqrt(drawingIds.length)))
    const byDrawing = new Map<string, ExtractedNode[]>()
    nodes.forEach(n => {
      const d = n.drawing ?? 'unknown'
      const arr = byDrawing.get(d) ?? []
      arr.push(n)
      byDrawing.set(d, arr)
    })
    const cellOf = new Map(drawingIds.map(d =>
      [d, cellSizeFor(byDrawing.get(d) ?? [])] as const))

    const colW: number[] = []
    const rowH: number[] = []
    drawingIds.forEach((d, i) => {
      const col = i % COLS
      const row = Math.floor(i / COLS)
      const c = cellOf.get(d)!
      colW[col] = Math.max(colW[col] ?? 0, c.w)
      rowH[row] = Math.max(rowH[row] ?? 0, c.h)
    })
    const colX: number[] = []
    let accX = EXTRACTED_MARGIN
    for (let c = 0; c < COLS; c++) { colX[c] = accX; accX += (colW[c] ?? CELL_W) + CELL_GAP }
    const rowY: number[] = []
    let accY = EXTRACTED_MARGIN
    for (let r = 0; r < rowH.length; r++) { rowY[r] = accY; accY += (rowH[r] ?? CELL_H) + CELL_GAP }

    const offsetMap = new Map(drawingIds.map((d, i) => [d, {
      ox: colX[i % COLS],
      oy: rowY[Math.floor(i / COLS)],
    }]))

    nodes.forEach(n => {
      const { w, h } = getSize(n)
      const key = n.drawing ?? 'unknown'
      const { ox, oy } = offsetMap.get(key) ?? { ox: 0, oy: 0 }
      const cell = cellOf.get(key) ?? { w: CELL_W, h: CELL_H }
      const cx = ox + (n.x ?? 0.5) * cell.w
      const cy = oy + (n.y ?? 0.5) * cell.h
      pos.set(n.id, { x: cx - w / 2, y: cy - h / 2 })
    })

    const sizes = packVendorPackages(nodes, pos, getSize)
    return { pos, sizes }
  }

  // Single drawing — map [0,1] coords to canvas dimensions
  const usableW = Math.max(canvasW - 2 * EXTRACTED_MARGIN, 400)
  const usableH = Math.max(canvasH - 2 * EXTRACTED_MARGIN, 300)

  nodes.forEach(n => {
    const { w, h } = getSize(n)
    // Clamp coords into [0,1] — the LLM occasionally emits y>1 (e.g. 1.03),
    // which would render the symbol below the canvas edge and clip it.
    const nx = clamp01(n.x ?? 0.5)
    const ny = clamp01(n.y ?? 0.5)
    const cx = EXTRACTED_MARGIN + nx * usableW
    const cy = EXTRACTED_MARGIN + ny * usableH
    pos.set(n.id, { x: cx - w / 2, y: cy - h / 2 })
  })

  // Establish pipe-run alignment FIRST, from the raw extracted geometry — this
  // is the truest signal for "meant to be a straight line" because nothing has
  // pushed these symbols around yet.
  const alignGroups = edges.length
    ? computeAlignGroups(nodes, edges, pos, getSize)
    : { H: new Map<string, string>(), V: new Map<string, string>() }
  if (edges.length) snapAlignGroups(nodes, alignGroups, pos, getSize)

  // Root membership counts — a union-find root is an arbitrary member, so
  // "same root" alone doesn't mean "actually grouped" (a lone, un-unioned node
  // is its own root too). Only roots with ≥2 members represent a real run.
  const rootSize = (p: Map<string, string>) => {
    const m = new Map<string, number>()
    nodes.forEach(n => { const r = ufFind(p, n.id); m.set(r, (m.get(r) ?? 0) + 1) })
    return m
  }
  const hSize = rootSize(alignGroups.H)
  const vSize = rootSize(alignGroups.V)

  // ── Overlap resolution — skip vendor-package children (packed separately) ──
  // Group-aware: two symbols that belong to the same pipe run (same H/V align
  // group) must not be pushed apart along the axis that keeps them colinear —
  // that's exactly what used to happen in dense clusters (many collisions
  // forced a bigger push, exceeding the alignment pass and leaving the pipe
  // visibly broken) while sparser areas, pushed less, stayed aligned by luck.
  // Locked-axis pairs only separate along the free axis; everything else still
  // resolves by least-penetration as before.
  const byId = new Map(nodes.map(n => [n.id, n]))
  const isPackChild = (n: ExtractedNode) => {
    if (!n.equipment_ref) return false
    const refKind = byId.get(n.equipment_ref)?.kind
    return refKind === 'vendor_package' || refKind === 'package'
  }
  const resolvable = nodes.filter(n => !isPackChild(n) && n.kind !== 'vendor_package' && n.kind !== 'package')

  const ITERS = 50
  const PADDING = 10
  for (let i = 0; i < ITERS; i++) {
    let moved = false
    for (let j = 0; j < resolvable.length; j++) {
      for (let k = j + 1; k < resolvable.length; k++) {
        const n1 = resolvable[j]
        const n2 = resolvable[k]
        const p1 = pos.get(n1.id)!
        const p2 = pos.get(n2.id)!
        const s1 = getSize(n1)
        const s2 = getSize(n2)

        const r1 = { l: p1.x, r: p1.x + s1.w, t: p1.y, b: p1.y + s1.h }
        const r2 = { l: p2.x, r: p2.x + s2.w, t: p2.y, b: p2.y + s2.h }

        if (r1.l < r2.r + PADDING && r1.r > r2.l - PADDING && r1.t < r2.b + PADDING && r1.b > r2.t - PADDING) {
          const c1x = p1.x + s1.w / 2
          const c1y = p1.y + s1.h / 2
          const c2x = p2.x + s2.w / 2
          const c2y = p2.y + s2.h / 2
          let dx = c2x - c1x
          let dy = c2y - c1y
          if (dx === 0 && dy === 0) { dx = Math.random() - 0.5; dy = Math.random() - 0.5 }

          const hRoot = ufFind(alignGroups.H, n1.id)
          const vRoot = ufFind(alignGroups.V, n1.id)
          const sameH = hRoot === ufFind(alignGroups.H, n2.id) && (hSize.get(hRoot) ?? 0) >= 2
          const sameV = vRoot === ufFind(alignGroups.V, n2.id) && (vSize.get(vRoot) ?? 0) >= 2
          if (sameH) dy = 0
          else if (sameV) dx = 0
          if (dx === 0 && dy === 0) continue
          moved = true

          const dist = Math.sqrt(dx * dx + dy * dy)
          const pushAmount = 4
          const nx = (dx / dist) * pushAmount
          const ny = (dy / dist) * pushAmount

          pos.set(n1.id, { x: p1.x - nx, y: p1.y - ny })
          pos.set(n2.id, { x: p2.x + nx, y: p2.y + ny })
        }
      }
    }
    if (!moved) break
  }

  // Final safety re-snap using the SAME groups computed on raw geometry — the
  // group-aware push above should already preserve alignment, this just
  // cleans up any residual sub-pixel drift from perpendicular-only pushes.
  if (edges.length) snapAlignGroups(nodes, alignGroups, pos, getSize)

  const sizes = packVendorPackages(nodes, pos, getSize)
  return { pos, sizes }
}

/** Convert React Flow top-left position back to 0–1 sheet coords (after drag). */
export function pixelToNormalized(
  px: number,
  py: number,
  w: number,
  h: number,
  canvasW: number,
  canvasH: number,
): { x: number; y: number } {
  const usableW = Math.max(canvasW - 2 * EXTRACTED_MARGIN, 400)
  const usableH = Math.max(canvasH - 2 * EXTRACTED_MARGIN, 300)
  const cx = px + w / 2
  const cy = py + h / 2
  return {
    x: clamp01((cx - EXTRACTED_MARGIN) / usableW),
    y: clamp01((cy - EXTRACTED_MARGIN) / usableH),
  }
}

/** Convert a single 0–1 sheet point (no width/height) to flow pixels — the
 * inverse of pixelToNormalized's center math, for point data like an edge
 * bend rather than a sized node box. */
export function normalizedPointToPixel(
  nx: number, ny: number, canvasW: number, canvasH: number,
): { x: number; y: number } {
  const usableW = Math.max(canvasW - 2 * EXTRACTED_MARGIN, 400)
  const usableH = Math.max(canvasH - 2 * EXTRACTED_MARGIN, 300)
  return { x: EXTRACTED_MARGIN + nx * usableW, y: EXTRACTED_MARGIN + ny * usableH }
}

/** Inverse of normalizedPointToPixel. */
export function pixelPointToNormalized(
  px: number, py: number, canvasW: number, canvasH: number,
): { x: number; y: number } {
  const usableW = Math.max(canvasW - 2 * EXTRACTED_MARGIN, 400)
  const usableH = Math.max(canvasH - 2 * EXTRACTED_MARGIN, 300)
  return {
    x: clamp01((px - EXTRACTED_MARGIN) / usableW),
    y: clamp01((py - EXTRACTED_MARGIN) / usableH),
  }
}

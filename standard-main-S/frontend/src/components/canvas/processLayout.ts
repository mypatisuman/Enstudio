/**
 * processLayout.ts — Process-aware P&ID layout engine v2.
 *
 * Implements rules from studio/skills/reconstruction/process-reconstruction.md:
 *   backbone:    y=300 per row, x_start=200, x_step=250
 *   multi-row:   disconnected equipment components each get their own row (200px apart)
 *   instruments: 120px below backbone (controllers 200px), centered spread
 *   valves:      inline on backbone at midpoint of neighbours
 *   off-page:    sources left x=50, sinks right x=maxEquipX+200, stacked 50px apart
 */

import { getNodeType, getNodeSize } from './ISANodes'

export interface PlNode {
  id:            string
  label:         string
  kind:          string
  equipment_ref: string
  area?:         string
  drawing?:      string   // drawing number the node belongs to
}
export interface PlEdge {
  source: string
  target: string
  kind:   string
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ROW_BASE_Y  = 300    // first backbone row Y
const ROW_SPACING = 400    // vertical gap between backbone rows
const X_START     = 200    // first equipment x
const X_STEP      = 250    // minimum equipment x step
const INSTR_DY    = 120    // transmitters/indicators below backbone
const CTRL_DY     = 200    // controllers further below backbone
const SPREAD_DX   = 100    // horizontal spread per instrument slot
const OP_STACK_DY = 50     // off-page vertical stacking interval

// ── Kind classification ───────────────────────────────────────────────────────

const EQUIP_KINDS = new Set([
  'vessel','separator','pump','heat_exchanger','compressor','column','reactor',
  'absorber','adsorption','filter','meter','drum','tank','fired_heater','boiler','air_cooler',
  'vessel_v','vessel_h','flash_drum','knockout','accumulator','tank_atm','hopper',
  'dist_tray','dist_packed','scrubber','stripper',
  'cstr','pfr','fixed_bed','fluidized_bed','batch_reactor',
  'hx_st','hx_plate','condenser','reboiler_k',
  'pump_cent','pump_pd','mixer','blower',
  'comp_cent','comp_recip',
  'cyclone','filter_pf','centrifuge','membrane',
])

const INSTR_KINDS = new Set([
  'transmitter','controller','indicator','recorder','switch',
  'analyzer','element','instrument','alarm',
  'ft','lt','pt','tt','at','fe','le','pe','te',
  'fic','pic','tic','lic','aic',
  'fi','pi','ti','li','ai',
  'fr','pr','tr','lr','ar',
  'fsh','fsl','psh','psl','tsh','tsl','lsh','lsl',
  'dcs','plc','sis',
])

const VALVE_KINDS = new Set([
  'control_valve','hand_valve','check_valve','solenoid_valve',
  'relief_valve','checkvalve','valve','relief','psv','rupture_disc',
  'cv_globe','cv_ball','cv_butterfly','cv_gate',
])

const CTRL_KINDS = new Set([
  'controller','fic','pic','tic','lic','aic','dcs','plc','sis',
])

const PROCESS_EDGE_KINDS = new Set(['stream','process','bypass','recycle',''])

function isEquip   (kind: string): boolean { return EQUIP_KINDS.has(kind.toLowerCase()) }
function isInstr   (kind: string): boolean { return INSTR_KINDS.has(kind.toLowerCase()) }
function isValve   (kind: string): boolean { return VALVE_KINDS.has(kind.toLowerCase()) }
function isOffPage (label: string): boolean { return /off.?page/i.test(label) }
function isCtrl    (kind: string): boolean { return CTRL_KINDS.has(kind.toLowerCase()) }

// ── Helpers ───────────────────────────────────────────────────────────────────

function loopPrefix(label: string): string {
  const m = label.match(/-(\d+)/)
  return m ? m[1].slice(0, 2) : ''
}

function tagNum(label: string): number {
  const m = label.match(/\d+/)
  return m ? parseInt(m[0], 10) : 9999
}

// ── Connected components of equipment ────────────────────────────────────────
//
// Uses ALL edge types (process + signal + assoc) — a pair of equipment nodes
// is only "disconnected" if there is absolutely no edge of any kind between them.
// Small drawings (< 4 equipment) and groups smaller than 2 are merged onto one row.

function findEquipComponents(equip: PlNode[], edges: PlEdge[]): PlNode[][] {
  // Small drawings: never split
  if (equip.length < 4) {
    return [equip.slice().sort((a, b) => tagNum(a.label) - tagNum(b.label))]
  }

  const ids = new Set(equip.map(n => n.id))
  const adj = new Map<string, Set<string>>()
  equip.forEach(n => adj.set(n.id, new Set()))

  // Accept ALL edge kinds — component boundary only where NO edge exists at all
  edges.forEach(e => {
    if (!ids.has(e.source) || !ids.has(e.target)) return
    adj.get(e.source)!.add(e.target)
    adj.get(e.target)!.add(e.source)
  })

  const visited = new Set<string>()
  const rawComponents: PlNode[][] = []

  for (const node of equip) {
    if (visited.has(node.id)) continue
    const component: PlNode[] = []
    const queue = [node]
    visited.add(node.id)
    while (queue.length) {
      const n = queue.shift()!
      component.push(n)
      for (const nbId of adj.get(n.id) ?? new Set<string>()) {
        if (!visited.has(nbId)) {
          visited.add(nbId)
          const nb = equip.find(e => e.id === nbId)
          if (nb) queue.push(nb)
        }
      }
    }
    rawComponents.push(component)
  }

  // Only split into separate rows if each group has >= 2 equipment nodes.
  // Singleton components are merged into the first substantial group.
  const meaningful = rawComponents.filter(c => c.length >= 2)
  const singletons = rawComponents.filter(c => c.length < 2)

  if (meaningful.length <= 1) {
    // Everything on one backbone row
    return [equip.slice().sort((a, b) => tagNum(a.label) - tagNum(b.label))]
  }

  // Attach singletons to the component whose min tag number is closest
  singletons.forEach(sg => {
    const sgMin = tagNum(sg[0].label)
    let closest = meaningful[0]
    let bestDist = Infinity
    meaningful.forEach(comp => {
      const dist = Math.abs(Math.min(...comp.map(n => tagNum(n.label))) - sgMin)
      if (dist < bestDist) { bestDist = dist; closest = comp }
    })
    closest.push(...sg)
  })

  // Sort: component with lowest tag number first (main flow first)
  meaningful.sort((a, b) =>
    Math.min(...a.map(n => tagNum(n.label))) -
    Math.min(...b.map(n => tagNum(n.label)))
  )

  return meaningful
}

// ── Topological sort within one equipment component ───────────────────────────

function topoSortEquipment(equip: PlNode[], edges: PlEdge[]): PlNode[] {
  const ids   = new Set(equip.map(n => n.id))
  const adj   = new Map<string, string[]>()
  const indeg = new Map<string, number>()
  equip.forEach(n => { adj.set(n.id, []); indeg.set(n.id, 0) })

  edges.forEach(e => {
    if (!ids.has(e.source) || !ids.has(e.target)) return
    const k = (e.kind ?? '').toLowerCase()
    if (!PROCESS_EDGE_KINDS.has(k) && k !== 'bypass' && k !== 'recycle') return
    adj.get(e.source)!.push(e.target)
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
  })

  const queue: PlNode[] = equip
    .filter(n => (indeg.get(n.id) ?? 0) === 0)
    .sort((a, b) => tagNum(a.label) - tagNum(b.label))

  const result: PlNode[] = []

  while (queue.length) {
    const node = queue.shift()!
    result.push(node)
    const neighbours = (adj.get(node.id) ?? [])
      .map(id => equip.find(n => n.id === id)!)
      .filter(Boolean)
      .sort((a, b) => tagNum(a.label) - tagNum(b.label))

    for (const nb of neighbours) {
      const deg = (indeg.get(nb.id) ?? 0) - 1
      indeg.set(nb.id, deg)
      if (deg === 0) {
        const insertAt = queue.findIndex(q => tagNum(q.label) > tagNum(nb.label))
        if (insertAt === -1) queue.push(nb)
        else queue.splice(insertAt, 0, nb)
      }
    }
  }

  // Append cycle / island nodes in tag-number order
  if (result.length < equip.length) {
    const placed = new Set(result.map(n => n.id))
    equip
      .filter(n => !placed.has(n.id))
      .sort((a, b) => tagNum(a.label) - tagNum(b.label))
      .forEach(n => result.push(n))
  }

  return result
}

// ── Main layout function ──────────────────────────────────────────────────────

export function processLayout(
  nodes: PlNode[],
  edges: PlEdge[],
): Map<string, { x: number; y: number }> {
  const pos   = new Map<string, { x: number; y: number }>()
  const byId  = new Map(nodes.map(n => [n.id, n]))
  const byLbl = new Map(nodes.map(n => [n.label, n]))

  // ── Classify ──────────────────────────────────────────────────────────────
  const equip    = nodes.filter(n => isEquip(n.kind)  && !isOffPage(n.label))
  const instrs   = nodes.filter(n => isInstr(n.kind)  && !isOffPage(n.label))
  const valves   = nodes.filter(n => isValve(n.kind)  && !isOffPage(n.label))
  const offPages = nodes.filter(n => isOffPage(n.label))
  const equipIds = new Set(equip.map(n => n.id))

  // ── Pre-calculate instruments per equipment to adjust horizontal spacing ──
  function findParentEquip(instr: PlNode): PlNode | null {
    if (instr.equipment_ref) {
      const ref = byLbl.get(instr.equipment_ref) ?? equip.find(e => e.label === instr.equipment_ref)
      if (ref && equipIds.has(ref.id)) return ref
    }
    const iPrefix = loopPrefix(instr.label)
    if (iPrefix) {
      const matches = equip.filter(e => loopPrefix(e.label) === iPrefix)
      if (matches.length === 1) return matches[0]
      if (matches.length > 1) {
        const sameArea = matches.filter(e => e.area && instr.area && e.area === instr.area)
        return sameArea[0] ?? matches[0]
      }
    }
    for (const e of edges) {
      if (e.source === instr.id && equipIds.has(e.target)) return byId.get(e.target) ?? null
      if (e.target === instr.id && equipIds.has(e.source)) return byId.get(e.source) ?? null
    }
    if (instr.area) {
      const sameArea = equip.filter(e => e.area === instr.area)
      if (sameArea.length) return sameArea[0]
    }
    return null
  }

  const instrTotal  = new Map<string, number>()
  instrs.forEach(n => {
    const parent = findParentEquip(n)
    if (parent) instrTotal.set(parent.id, (instrTotal.get(parent.id) ?? 0) + 1)
  })

  // ── Equipment: one backbone row per connected component ────────────────────
  const equipX    = new Map<string, number>()  // equipId → backbone x
  const equipRowY = new Map<string, number>()  // equipId → backbone y

  const components = findEquipComponents(equip, edges)

  components.forEach((component, rowIdx) => {
    const rowY  = ROW_BASE_Y + rowIdx * ROW_SPACING
    const sorted = topoSortEquipment(component, edges)
    let currentX = X_START
    sorted.forEach((n, i) => {
      if (i > 0) {
        const prevTotal = instrTotal.get(sorted[i-1].id) ?? 0
        const currTotal = instrTotal.get(n.id) ?? 0
        const prevReq = Math.max(X_STEP, prevTotal * SPREAD_DX + 50)
        const currReq = Math.max(X_STEP, currTotal * SPREAD_DX + 50)
        currentX += (prevReq / 2) + (currReq / 2)
      }
      equipX.set(n.id, currentX)
      equipRowY.set(n.id, rowY)
      pos.set(n.id, { x: currentX, y: rowY })
    })
  })

  let trueMaxX = X_START
  for (const [eqId, x] of equipX.entries()) {
    const total = instrTotal.get(eqId) ?? 0
    const rightEdge = x + (total * SPREAD_DX) / 2
    trueMaxX = Math.max(trueMaxX, rightEdge)
  }
  const rightBufferX = trueMaxX + 200

  // ── Off-page connectors ────────────────────────────────────────────────────
  // Source = no incoming from real nodes  →  left edge (x=50), stacked vertically
  // Sink   = has incoming from real nodes →  right edge, stacked vertically
  const nonOPIds   = new Set(nodes.filter(n => !isOffPage(n.label)).map(n => n.id))
  const opIncoming = new Map<string, number>()
  offPages.forEach(n => opIncoming.set(n.id, 0))

  edges.forEach(e => {
    const tgt = byId.get(e.target)
    if (tgt && isOffPage(tgt.label) && nonOPIds.has(e.source))
      opIncoming.set(e.target, (opIncoming.get(e.target) ?? 0) + 1)
  })

  let srcIdx = 0, sinkIdx = 0
  offPages.forEach(n => {
    if ((opIncoming.get(n.id) ?? 0) === 0) {
      pos.set(n.id, { x: 50, y: ROW_BASE_Y + srcIdx * OP_STACK_DY })
      srcIdx++
    } else {
      pos.set(n.id, { x: rightBufferX + 150, y: ROW_BASE_Y + sinkIdx * OP_STACK_DY })
      sinkIdx++
    }
  })

  // ── Control valves inline on their row's backbone ─────────────────────────
  const valvePlacementCount = new Map<string, number>()

  valves.forEach(n => {
    const adjInfo: Array<{ x: number; y: number }> = []
    edges.forEach(e => {
      const check = (eqId: string) => {
        const x = equipX.get(eqId)
        const y = equipRowY.get(eqId)
        if (x !== undefined && y !== undefined) adjInfo.push({ x, y })
      }
      if (e.source === n.id && equipIds.has(e.target)) check(e.target)
      if (e.target === n.id && equipIds.has(e.source)) check(e.source)
    })

    let baseX: number, baseY: number, baseKey: string
    if (adjInfo.length >= 2) {
      const xs = adjInfo.map(p => p.x)
      baseX = (Math.min(...xs) + Math.max(...xs)) / 2
      baseY = adjInfo[0].y
      baseKey = `2-${baseX}-${baseY}`
    } else if (adjInfo.length === 1) {
      baseX = adjInfo[0].x + X_STEP * 0.4
      baseY = adjInfo[0].y
      baseKey = `1-${baseX}-${baseY}`
    } else {
      baseX = rightBufferX
      baseY = ROW_BASE_Y
      baseKey = `0-${baseX}-${baseY}`
    }

    const count = valvePlacementCount.get(baseKey) ?? 0
    valvePlacementCount.set(baseKey, count + 1)

    // Arrange multiple valves at the same spot into a neat grid instead of overlapping
    const cols = 3
    const row = Math.floor(count / cols)
    const col = count % cols

    // Shift slightly so the first valve is at the exact midpoint
    const offsetX = col * 80 - (count > 0 && cols > 1 ? 40 : 0)
    const offsetY = row * 80

    pos.set(n.id, { x: baseX + offsetX, y: baseY + offsetY })
  })

  // Sort: equipment_ref ones first, then by tag number
  const instrSorted = [...instrs].sort((a, b) => {
    const aRef = a.equipment_ref ? 0 : 1
    const bRef = b.equipment_ref ? 0 : 1
    return (aRef - bRef) || tagNum(a.label) - tagNum(b.label)
  })

  // Second pass: place with centered spread
  const instrPlaced = new Map<string, number>()
  instrSorted.forEach(n => {
    const parent = findParentEquip(n)
    if (!parent || !pos.has(parent.id)) return

    const total = instrTotal.get(parent.id) ?? 1
    const pX    = pos.get(parent.id)!.x
    const rowY  = equipRowY.get(parent.id) ?? ROW_BASE_Y
    const idx   = instrPlaced.get(parent.id) ?? 0
    instrPlaced.set(parent.id, idx + 1)

    // FIX 4: Centered spread — instruments fan symmetrically around equipment
    const spread = (idx - (total - 1) / 2) * SPREAD_DX
    const dy     = isCtrl(n.kind) ? CTRL_DY : INSTR_DY

    pos.set(n.id, { x: pX + spread, y: rowY + dy })
  })

  // ── Residual: anything unplaced goes below all rows ────────────────────────
  const numRows    = Math.max(1, components.length)
  const residualY  = ROW_BASE_Y + numRows * ROW_SPACING + 50

  nodes
    .filter(n => !pos.has(n.id))
    .sort((a, b) => tagNum(a.label) - tagNum(b.label))
    .forEach((n, i) => {
      pos.set(n.id, { x: X_START + i * Math.round(X_STEP * 0.7), y: residualY })
    })

  // ── Precise overlap resolution to guarantee clear spacing ───────────────────
  const ITERS = 100
  const PADDING = 20
  for (let i = 0; i < ITERS; i++) {
    let moved = false
    for (let j = 0; j < nodes.length; j++) {
      for (let k = j + 1; k < nodes.length; k++) {
        const n1 = nodes[j]
        const n2 = nodes[k]
        const p1 = pos.get(n1.id)
        const p2 = pos.get(n2.id)
        if (!p1 || !p2) continue

        const type1 = getNodeType(n1.kind, n1.label, isOffPage(n1.label))
        const type2 = getNodeType(n2.kind, n2.label, isOffPage(n2.label))
        const s1 = getNodeSize(type1, 0)
        const s2 = getNodeSize(type2, 0)

        const c1x = p1.x + s1.w / 2
        const c1y = p1.y + s1.h / 2
        const c2x = p2.x + s2.w / 2
        const c2y = p2.y + s2.h / 2

        const dx = c2x - c1x
        const dy = c2y - c1y
        const overlapX = (s1.w / 2 + s2.w / 2 + PADDING) - Math.abs(dx)
        const overlapY = (s1.h / 2 + s2.h / 2 + PADDING) - Math.abs(dy)

        if (overlapX > 0 && overlapY > 0) {
          moved = true
          // Push along the axis of least penetration
          if (overlapX < overlapY) {
            const push = (overlapX / 2) + 1
            const dir = dx >= 0 ? 1 : -1
            pos.set(n1.id, { x: p1.x - push * dir, y: p1.y })
            pos.set(n2.id, { x: p2.x + push * dir, y: p2.y })
          } else {
            const push = (overlapY / 2) + 1
            const dir = dy >= 0 ? 1 : -1
            pos.set(n1.id, { x: p1.x, y: p1.y - push * dir })
            pos.set(n2.id, { x: p2.x, y: p2.y + push * dir })
          }
        }
      }
    }
    if (!moved) break
  }

  return pos
}

/**
 * Returns true if there are enough equipment nodes for a meaningful backbone layout.
 */
export function canUseProcessLayout(nodes: PlNode[]): boolean {
  return nodes.filter(n => isEquip(n.kind) && !isOffPage(n.label)).length >= 2
}

// ── Plant-wide layout (all drawings) ─────────────────────────────────────────
// Each process area occupies a fixed 1500px column.  Multiple drawings in the
// same area stack vertically at 600px intervals.  Utility areas sit 900px below.

export type AreaCategory =
  | 'FEED' | 'METERING' | 'COMPRESSION' | 'PREHEAT' | 'REACTOR'
  | 'SEPARATION' | 'ANALYTICS'
  | 'UTILITY_CW' | 'UTILITY_HOT' | 'UTILITY_AIR'
  | 'UTILITY_VENT' | 'UTILITY_N2' | 'UTILITY_ELEC'
  | 'OTHER'

export interface AreaGroup {
  category: AreaCategory
  x:        number
  y:        number
  width:    number
  height:   number
  label:    string
  color:    string
}

// ISA area colours — subtle fills for group backgrounds
const AREA_COLORS: Record<AreaCategory, string> = {
  FEED:         'rgba(14,165,233,0.07)',
  METERING:     'rgba(14,165,233,0.05)',
  COMPRESSION:  'rgba(99,102,241,0.08)',
  PREHEAT:      'rgba(34,197,94,0.06)',
  REACTOR:      'rgba(239,68,68,0.07)',
  SEPARATION:   'rgba(34,197,94,0.07)',
  ANALYTICS:    'rgba(234,179,8,0.07)',
  OTHER:        'rgba(100,116,139,0.05)',
  UTILITY_CW:   'rgba(100,116,139,0.05)',
  UTILITY_HOT:  'rgba(100,116,139,0.05)',
  UTILITY_AIR:  'rgba(100,116,139,0.05)',
  UTILITY_VENT: 'rgba(100,116,139,0.05)',
  UTILITY_N2:   'rgba(100,116,139,0.05)',
  UTILITY_ELEC: 'rgba(100,116,139,0.05)',
}

const AREA_LABELS: Record<AreaCategory, string> = {
  FEED:         'Feed / Delivery',
  METERING:     'Metering',
  COMPRESSION:  'Compression',
  PREHEAT:      'Preheat',
  REACTOR:      'Reactor',
  SEPARATION:   'Separation',
  ANALYTICS:    'Analytics',
  OTHER:        'Other',
  UTILITY_CW:   'Cooling Water',
  UTILITY_HOT:  'Hot Oil / Heating',
  UTILITY_AIR:  'Instrument Air',
  UTILITY_VENT: 'Vent / Flare',
  UTILITY_N2:   'Nitrogen',
  UTILITY_ELEC: 'Electrical',
}

// Main process areas (ordered left → right in plant flow)
const MAIN_AREAS: AreaCategory[] = [
  'FEED','METERING','COMPRESSION','PREHEAT','REACTOR','SEPARATION','ANALYTICS','OTHER',
]
// Utility areas (rendered below main process)
const UTILITY_AREAS: AreaCategory[] = [
  'UTILITY_CW','UTILITY_HOT','UTILITY_AIR','UTILITY_VENT','UTILITY_N2','UTILITY_ELEC',
]

// Fixed x column per area category (left-to-right plant flow)
const AREA_X: Record<AreaCategory, number> = {
  FEED:         0,
  METERING:     1500,
  COMPRESSION:  3000,
  PREHEAT:      4500,
  REACTOR:      6000,
  SEPARATION:   7500,
  ANALYTICS:    9000,
  OTHER:        10500,
  UTILITY_CW:   0,
  UTILITY_HOT:  2000,
  UTILITY_AIR:  4000,
  UTILITY_VENT: 6000,
  UTILITY_N2:   8000,
  UTILITY_ELEC: 10000,
}

const UTILITY_Y       = ROW_BASE_Y + 900  // utility backbone y (= 1200)
const AREA_COL_WIDTH  = 1500              // fixed width per area column
const DRAWING_ROW_H   = 600              // vertical slot per drawing within an area
const GROUP_PAD_X     = 60              // horizontal padding around area group rect
const GROUP_PAD_Y_TOP = 80              // space above backbone for group label

/**
 * Classify a drawing by its area name or title string.
 * Accepts area field values ("RECYCLE COMPRESSOR SECTION") or drawing numbers.
 */
export function classifyDrawingArea(text: string): AreaCategory {
  const t = text.toLowerCase()
  if (/feed|delivery|storage|supply\b/.test(t) && !/hot|heat|coolant/.test(t)) return 'FEED'
  if (/meter|metering/.test(t))                                                  return 'METERING'
  if (/compress|recycle/.test(t))                                                return 'COMPRESSION'
  if (/preheat|feed.?heat/.test(t))                                              return 'PREHEAT'
  if (/reactor|reaction/.test(t))                                                return 'REACTOR'
  if (/separat|product|collection|absorb|distill/.test(t))                       return 'SEPARATION'
  if (/analytic|sampling|gas.?anal/.test(t))                                     return 'ANALYTICS'
  if (/cool|chiller|glycol|cooling.?water/.test(t))                             return 'UTILITY_CW'
  if (/hot.?oil|heat.?medium|thermal.?fluid/.test(t))                           return 'UTILITY_HOT'
  if (/instrument.?air|air.?compress/.test(t))                                   return 'UTILITY_AIR'
  if (/vent|relief.?head|flare/.test(t))                                         return 'UTILITY_VENT'
  if (/nitrogen|n2\b/.test(t))                                                   return 'UTILITY_N2'
  if (/electr|cabinet|power|mcc/.test(t))                                        return 'UTILITY_ELEC'
  return 'OTHER'
}

/** Most common non-empty string in an array. */
function mostCommon(arr: string[]): string {
  const counts = new Map<string, number>()
  arr.forEach(v => { if (v) counts.set(v, (counts.get(v) ?? 0) + 1) })
  let best = '', bestN = 0
  for (const [v, n] of counts) { if (n > bestN) { bestN = n; best = v } }
  return best
}

/**
 * Plant-wide layout: positions all nodes across all drawings in a left-to-right
 * process flow arrangement, with utilities below.
 *
 * Each area has a FIXED x column (per AREA_X).  Multiple drawings in the same
 * area stack vertically at DRAWING_ROW_H intervals.
 *
 * @param nodes       All graph nodes (must include `drawing` field)
 * @param edges       All edges (cross-drawing edges not used for per-drawing layout)
 * @param drawingMeta Optional: { [drawingId]: {title?, area?} }
 */
export function plantLayout(
  nodes: PlNode[],
  edges: PlEdge[],
  drawingMeta: Record<string, {title?: string; area?: string}> = {},
): { pos: Map<string, {x: number; y: number}>; groups: AreaGroup[] } {

  const pos    = new Map<string, {x: number; y: number}>()
  const groups: AreaGroup[] = []

  // ── FIX B: use `||` not `??` to treat empty-string drawing same as missing ──
  const byDrawing = new Map<string, PlNode[]>()
  nodes.forEach(n => {
    const drw = n.drawing || '_unknown'
    if (!byDrawing.has(drw)) byDrawing.set(drw, [])
    byDrawing.get(drw)!.push(n)
  })

  // ── FIX A: three-tier classification ────────────────────────────────────────
  // Tier 1: area name from drawingMeta (title or explicit area)
  // Tier 2: most-common node.area in this drawing
  // Tier 3: equipment kind-based fallback (compressors → COMPRESSION, etc.)
  function classifyDrawing(drw: string, dnodes: PlNode[]): AreaCategory {
    // Tier 1: explicit meta
    const meta = drawingMeta[drw]
    if (meta?.area) {
      const c = classifyDrawingArea(meta.area)
      if (c !== 'OTHER') return c
    }
    if (meta?.title) {
      const c = classifyDrawingArea(meta.title)
      if (c !== 'OTHER') return c
    }

    // Tier 2: most-common node.area
    const commonArea = mostCommon(dnodes.map(n => n.area ?? ''))
    if (commonArea) {
      const c = classifyDrawingArea(commonArea)
      if (c !== 'OTHER') return c
    }

    // Tier 3: equipment kind signatures
    const equip = dnodes.filter(n => isEquip(n.kind) && !isOffPage(n.label))
    const hasKind = (...ks: string[]) => equip.some(n => ks.includes(n.kind.toLowerCase()))

    let cat: AreaCategory = 'OTHER'
    if (hasKind('compressor','comp_cent','comp_recip','blower'))               cat = 'COMPRESSION'
    else if (hasKind('reactor','cstr','pfr','fixed_bed','fluidized_bed','batch_reactor')) cat = 'REACTOR'
    else if (hasKind('heat_exchanger','hx_st','hx_plate','condenser','reboiler_k','fired_heater','boiler','air_cooler') &&
             equip.length >= 2)                                                 cat = 'PREHEAT'
    else if (hasKind('column','absorber','adsorption','dist_tray','dist_packed','scrubber','stripper')) cat = 'SEPARATION'
    else if (hasKind('vessel','separator','flash_drum','knockout','accumulator') &&
             !hasKind('pump','pump_cent','pump_pd') && drw.includes('401'))    cat = 'SEPARATION'

    return cat
  }

  // Group drawings by category
  const byCategory = new Map<AreaCategory, string[]>()
  for (const [drw, dnodes] of byDrawing) {
    const cat = classifyDrawing(drw, dnodes)
    if (!byCategory.has(cat)) byCategory.set(cat, [])
    byCategory.get(cat)!.push(drw)
  }
  for (const [, drws] of byCategory) drws.sort()

  // ── FIX B: fixed area x columns, drawings stack vertically within column ────
  function layoutBand(categories: AreaCategory[], bandBaseY: number): void {
    for (const cat of categories) {
      const drws = byCategory.get(cat)
      if (!drws?.length) continue

      const areaX = AREA_X[cat]

      for (let di = 0; di < drws.length; di++) {
        const drw    = drws[di]
        const dnodes = byDrawing.get(drw)!
        const dIds   = new Set(dnodes.map(n => n.id))
        // Only internal edges for per-drawing layout
        const dEdges = edges.filter(e => dIds.has(e.source) && dIds.has(e.target))

        const drwPos = processLayout(dnodes, dEdges)

        // Left edge of processLayout output (off-pages land at x=50, equipment at x=200)
        let minX = Infinity
        for (const p of drwPos.values()) {
          minX = Math.min(minX, p.x)
        }
        if (!isFinite(minX)) { minX = X_START }

        // Target: drawing backbone aligns to areaX, stacked at di * DRAWING_ROW_H
        const targetBaseY = bandBaseY + di * DRAWING_ROW_H
        const xShift = areaX - minX
        const yShift = targetBaseY - ROW_BASE_Y   // ROW_BASE_Y is where processLayout sets backbone

        for (const [id, p] of drwPos) {
          pos.set(id, { x: p.x + xShift, y: p.y + yShift })
        }
      }

      // Area group background: fixed column width, height scales with drawing count
      const groupH = drws.length * DRAWING_ROW_H + GROUP_PAD_Y_TOP + 160
      groups.push({
        category: cat,
        x:        areaX - GROUP_PAD_X,
        y:        bandBaseY - GROUP_PAD_Y_TOP,
        width:    AREA_COL_WIDTH + GROUP_PAD_X * 2,
        height:   groupH,
        label:    AREA_LABELS[cat],
        color:    AREA_COLORS[cat],
      })
    }
  }

  layoutBand(MAIN_AREAS, ROW_BASE_Y)      // backbone y = 300
  layoutBand(UTILITY_AREAS, UTILITY_Y)    // backbone y = 1200

  // Any node not yet placed (no drawing, orphaned) — stack below utilities
  const residualY = UTILITY_Y + 600
  nodes
    .filter(n => !pos.has(n.id))
    .forEach((n, i) => pos.set(n.id, { x: i * 200, y: residualY }))

  return { pos, groups }
}

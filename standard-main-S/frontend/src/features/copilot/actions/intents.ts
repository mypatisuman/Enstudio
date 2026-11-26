import type { SearchFilter } from './search'

// Resolved intent for a user message. Deterministic (search/focus/validation/
// destructive) intents run locally and instantly; 'explain'/'summary'/'ask'
// route to the LLM. Parsing is a fast set of regexes — no LLM round-trip just
// to classify.
export type Intent =
  | { kind: 'search'; filter: SearchFilter }
  | { kind: 'focus'; tag: string }
  | { kind: 'explain'; tag: string }
  | { kind: 'summary'; drawing?: string }
  | { kind: 'validation'; severity?: 'critical' | 'warning' | 'info'; onlyOpen?: boolean; count?: boolean }
  | { kind: 'rename'; tag: string; newTag: string }
  | { kind: 'rename-bulk'; fromPrefix: string; toPrefix: string }
  | { kind: 'move'; tag: string; anchorTag?: string; dir?: string }
  | { kind: 'delete'; tags: string[] }
  | { kind: 'delete-unused' }
  | { kind: 'disconnect'; tag: string }
  | { kind: 'connect'; source: string; target: string }
  | { kind: 'duplicate'; tag: string }
  | { kind: 'layout'; op: 'align' | 'distribute' | 'auto-layout'; axis: 'h' | 'v'; filter: SearchFilter }
  | { kind: 'ask' }

// An ISA-ish tag token, e.g. "P-101", "FT 1043", "PIC-301".
const TAG = /\b([A-Za-z]{1,4}[\s-]?\d{2,4}[A-Za-z]?)\b/

// Ordered category matchers for "find/show/list/highlight all <X>". First hit
// wins, so put the more specific phrases first.
const CATEGORY_MATCHERS: { re: RegExp; filter: () => SearchFilter }[] = [
  { re: /pressure\s+transmitter/,      filter: () => ({ label: 'pressure transmitters', prefixStart: 'P', prefixEnd: 'T', category: 'instrument' }) },
  { re: /flow\s+transmitter/,          filter: () => ({ label: 'flow transmitters', prefixStart: 'F', prefixEnd: 'T', category: 'instrument' }) },
  { re: /level\s+transmitter/,         filter: () => ({ label: 'level transmitters', prefixStart: 'L', prefixEnd: 'T', category: 'instrument' }) },
  { re: /temperature\s+transmitter/,   filter: () => ({ label: 'temperature transmitters', prefixStart: 'T', prefixEnd: 'T', category: 'instrument' }) },
  { re: /transmitter/,                 filter: () => ({ label: 'transmitters', prefixEnd: 'T', category: 'instrument' }) },
  { re: /control(?:ler)?\s*loop|control\s+loop|controllers?/, filter: () => ({ label: 'control loops (controllers)', prefixEnd: 'C', category: 'instrument' }) },
  { re: /indicator/,                   filter: () => ({ label: 'indicators', prefixEnd: 'I', category: 'instrument' }) },
  { re: /(safety|relief)\s+valve/,     filter: () => ({ label: 'safety/relief valves', kinds: ['relief_valve', 'relief', 'psv', 'safety'] }) },
  { re: /control\s+valve/,             filter: () => ({ label: 'control valves', kinds: ['control_valve', 'control valve'] }) },
  { re: /valve/,                       filter: () => ({ label: 'valves', kinds: ['valve'] }) },
  { re: /pump/,                        filter: () => ({ label: 'pumps', kinds: ['pump'], category: 'equipment' }) },
  { re: /compressor/,                  filter: () => ({ label: 'compressors', kinds: ['compressor'], category: 'equipment' }) },
  { re: /heat\s+exchanger|exchanger/,  filter: () => ({ label: 'heat exchangers', kinds: ['heat_exchanger', 'exchanger'], category: 'equipment' }) },
  { re: /separator/,                   filter: () => ({ label: 'separators', kinds: ['separator'], category: 'equipment' }) },
  { re: /column|tower/,                filter: () => ({ label: 'columns', kinds: ['column', 'tower'], category: 'equipment' }) },
  { re: /reactor/,                     filter: () => ({ label: 'reactors', kinds: ['reactor'], category: 'equipment' }) },
  { re: /vessel|drum|tank/,            filter: () => ({ label: 'vessels', kinds: ['vessel', 'drum', 'tank'], category: 'equipment' }) },
]

function matchCategory(lower: string): SearchFilter | null {
  for (const m of CATEGORY_MATCHERS) if (m.re.test(lower)) return m.filter()
  return null
}

export function resolveIntent(raw: string): Intent {
  const t = raw.trim()
  const lower = t.toLowerCase()

  // ── Editing commands (previewed + confirmed via the command executor) ─────
  // Bulk rename by ISA prefix: "rename all/every FT to PIT"
  const bulk = /rename\s+(?:all|every)\s+([A-Za-z]{1,4})\s+(?:to|→|->)\s+([A-Za-z]{1,4})\b/i.exec(t)
  if (bulk) return { kind: 'rename-bulk', fromPrefix: bulk[1], toPrefix: bulk[2] }

  const rename = /rename\s+(.+?)\s+to\s+(.+)/i.exec(t)
  if (rename) return { kind: 'rename', tag: rename[1].trim(), newTag: rename[2].trim() }

  const move = /move\s+(.+?)\s+(?:near|beside|next\s+to|by|to)\s+(.+)/i.exec(t)
  if (move) {
    const anchor = (TAG.exec(move[2]) ?? [])[1]
    return { kind: 'move', tag: move[1].trim(), anchorTag: anchor ? anchor.trim() : move[2].trim(), dir: lower }
  }

  const dup = /(?:duplicate|clone|copy)\s+(.+)/i.exec(t)
  if (dup) { const m = TAG.exec(dup[1]); if (m) return { kind: 'duplicate', tag: m[1].trim() } }

  const disc = /disconnect\s+(.+)/i.exec(t)
  if (disc) { const m = TAG.exec(disc[1]); if (m) return { kind: 'disconnect', tag: m[1].trim() } }

  const connect = /connect\s+(.+?)\s+(?:to|and|with)\s+(.+)/i.exec(t)
  if (connect) {
    const a = (TAG.exec(connect[1]) ?? [])[1] ?? connect[1].trim()
    const b = (TAG.exec(connect[2]) ?? [])[1] ?? connect[2].trim()
    return { kind: 'connect', source: a, target: b }
  }

  // Layout ops on a category ("align all valves", "distribute pumps vertically").
  // Must precede the search branch, whose "all/every" also matches these.
  const layoutOp = /\balign\b/.test(lower) ? 'align'
    : /\bdistribute\b/.test(lower) ? 'distribute'
    : /auto[\s-]?(?:layout|arrange)/.test(lower) ? 'auto-layout' : null
  if (layoutOp) {
    const filter = matchCategory(lower)
    if (filter) {
      const axis: 'h' | 'v' = /vertical|column/.test(lower) ? 'v' : 'h'
      return { kind: 'layout', op: layoutOp, axis, filter }
    }
  }

  // Delete unused/floating symbols
  if (/(?:delete|remove|clear)\b.*\bunused\b|\bunused\b.*\bsymbols?\b/.test(lower)) {
    return { kind: 'delete-unused' }
  }

  // Delete specific tags
  if (/\b(delete|remove)\b/.test(lower)) {
    const tags = [...t.matchAll(new RegExp(TAG, 'g'))].map(m => m[1].trim())
    if (tags.length) return { kind: 'delete', tags }
  }

  // ── Object explanation (LLM) — also focuses the object ────────────────────
  if (/\bexplain\b/.test(lower)) {
    const m = TAG.exec(t)
    if (m) return { kind: 'explain', tag: m[1].trim() }
  }

  // ── Drawing summary (LLM) ─────────────────────────────────────────────────
  if (/summari[sz]e|summary|overview/.test(lower)) {
    const d = /drawing\s+([A-Za-z0-9\-_.]+)/i.exec(t)
    return { kind: 'summary', drawing: d ? d[1] : undefined }
  }

  // ── Validation questions (local, from cache) ──────────────────────────────
  if (/\bvalidation|issues?\b|warnings?\b|criticals?\b|disconnected\b|duplicate\b/.test(lower)) {
    const count = /how\s+many|number\s+of|count/.test(lower)
    if (/disconnected/.test(lower)) {
      return { kind: 'search', filter: { label: 'disconnected equipment', disconnectedTags: new Set() } }
    }
    if (/critical/.test(lower)) return { kind: 'validation', severity: 'critical', count }
    if (/warning/.test(lower))  return { kind: 'validation', severity: 'warning', onlyOpen: /remain|open|unresolved/.test(lower), count }
    if (/unresolved|open/.test(lower)) return { kind: 'validation', onlyOpen: true, count }
    if (/\bvalidation|issues?\b/.test(lower)) return { kind: 'validation', count }
  }

  // ── Low-confidence search ─────────────────────────────────────────────────
  if (/low[\s-]?confidence|uncertain/.test(lower)) {
    return { kind: 'search', filter: { label: 'low-confidence objects', lowConfidence: true } }
  }

  // ── Category search (find/show/list/highlight/locate all <X>) ─────────────
  const isSearchVerb = /\b(find|show|list|highlight|locate|select)\b/.test(lower) || /^every\b|\ball\b/.test(lower)
  if (isSearchVerb) {
    const filter = matchCategory(lower)
    if (filter) {
      const d = /drawing\s+([A-Za-z0-9\-_.]+)/i.exec(t)
      if (d) filter.drawing = d[1]
      return { kind: 'search', filter }
    }
    // "find equipment on drawing 2" with no type → drawing-only filter
    const d = /drawing\s+([A-Za-z0-9\-_.]+)/i.exec(t)
    if (d) return { kind: 'search', filter: { label: `objects on drawing ${d[1]}`, drawing: d[1] } }
  }

  // ── Single-object focus (show/zoom/center/locate/focus <TAG>) ─────────────
  if (/\b(show|zoom|center|centre|focus|locate|go\s+to|jump\s+to)\b/.test(lower)) {
    const m = TAG.exec(t)
    if (m) return { kind: 'focus', tag: m[1].trim() }
  }

  return { kind: 'ask' }
}

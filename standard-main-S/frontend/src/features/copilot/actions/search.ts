import type { ProjectContext } from '../context/projectContext'
import type { CopilotResult } from '../types'

// A unified, searchable view of every tagged symbol — built once from the
// context's raw arrays (which never leave the client). confidence/type are
// joined in from the instrument/equipment records by tag.
export interface SearchItem {
  tag: string
  category: string      // 'equipment' | 'instrument' | 'junction' | ...
  kind: string
  kindDetail: string
  type: string
  drawing: string
  confidence: number
  prefix: string        // leading ISA letters, e.g. "FT", "PIC" (digits stripped)
}

// What a search is looking for. Any subset of predicates; an item matches if it
// satisfies every predicate that is set.
export interface SearchFilter {
  label: string
  kinds?: string[]                 // substrings matched against kind/kindDetail/type
  prefixStart?: string             // ISA measured-variable letter, e.g. "P" (pressure)
  prefixEnd?: string               // ISA function letter, e.g. "T" (transmitter)
  category?: 'equipment' | 'instrument'
  drawing?: string
  lowConfidence?: boolean
  disconnectedTags?: Set<string>   // from validation issues
}

function alphaPrefix(tag: string): string {
  const m = /^[A-Za-z]+/.exec(tag.replace(/[\s\-_]/g, ''))
  return (m ? m[0] : '').toUpperCase()
}

export function buildSearchItems(ctx: ProjectContext): SearchItem[] {
  const confByTag = new Map(ctx.instruments.map(i => [i.tag, i.confidence]))
  const typeByTag = new Map<string, string>()
  for (const e of ctx.equipment)   typeByTag.set(e.tag, e.type || e.kind_detail)
  for (const i of ctx.instruments) typeByTag.set(i.tag, i.type || i.kind_detail)
  const detailByTag = new Map<string, string>()
  for (const e of ctx.equipment)   detailByTag.set(e.tag, e.kind_detail)
  for (const i of ctx.instruments) detailByTag.set(i.tag, i.kind_detail)

  return ctx.nodes
    .filter(n => n.label.trim())
    .map(n => ({
      tag: n.label,
      category: n.category,
      kind: n.kind,
      kindDetail: detailByTag.get(n.label) || n.kind_detail || '',
      type: typeByTag.get(n.label) || n.type || '',
      drawing: n.drawing || '',
      confidence: confByTag.get(n.label) ?? 0,
      prefix: alphaPrefix(n.label),
    }))
}

export function runSearch(items: SearchItem[], f: SearchFilter): SearchItem[] {
  const kinds = f.kinds?.map(k => k.toLowerCase())
  return items.filter(it => {
    if (f.category && it.category !== f.category) return false
    if (kinds) {
      const hay = `${it.kind} ${it.kindDetail} ${it.type}`.toLowerCase()
      if (!kinds.some(k => hay.includes(k))) return false
    }
    if (f.prefixStart && !it.prefix.startsWith(f.prefixStart)) return false
    if (f.prefixEnd && !it.prefix.endsWith(f.prefixEnd)) return false
    if (f.drawing && !it.drawing.toLowerCase().includes(f.drawing.toLowerCase())) return false
    if (f.lowConfidence && !(it.confidence > 0 && it.confidence < 0.7)) return false
    if (f.disconnectedTags && !f.disconnectedTags.has(it.tag)) return false
    return true
  })
}

export function toResults(items: SearchItem[]): CopilotResult[] {
  return items.map(it => ({
    tag: it.tag,
    title: it.tag,
    detail: [
      it.kindDetail || it.kind || it.category,
      it.drawing && `Drawing ${it.drawing}`,
      it.confidence > 0 && `${Math.round(it.confidence * 100)}%`,
    ].filter(Boolean).join(' · '),
  }))
}

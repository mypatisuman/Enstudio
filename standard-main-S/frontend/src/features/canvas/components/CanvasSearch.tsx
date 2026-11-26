import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import type { Node } from '@xyflow/react'
import type { CData } from '../types'

type Item = { id: string; label: string; kind: string }

/**
 * Canvas quick-search (Ctrl/Cmd+K). Filters the live nodes by tag/name/kind
 * and, on pick, hands the node id back so the canvas can highlight + animate-
 * focus to it. Self-contained: owns its own open state + key handling; renders
 * nothing until opened. Lives inside CanvasFlow so `nodes` reflects live edits.
 */
export function CanvasSearch({ nodes, onPick }: {
  nodes: Node<CData>[]
  onPick: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  // Element focused before the palette opened — restored on close so keyboard
  // focus doesn't get stranded on a removed node.
  const restoreFocusRef = useRef<HTMLElement | null>(null)

  // Opening from anywhere routes through this one setter — the Ctrl+K key
  // handler AND the toolbar button both call it, so there is exactly one
  // dialog / one open-state (no duplicated search).
  const openPalette = useCallback(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement
    setQ(''); setActive(0); setOpen(true)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) return
      // Don't hijack Ctrl+K while the user is typing in some OTHER field (tag
      // modal, top-bar search, etc.) — only when the palette itself isn't open.
      const el = e.target as HTMLElement | null
      const typingElsewhere = !!el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && !el.closest('.cvs-search')
      if (typingElsewhere && !open) return
      e.preventDefault()
      if (open) setOpen(false); else openPalette()
    }
    // Toolbar Search button (in the outer CanvasScreen, across the ReactFlow
    // boundary) dispatches this event instead of prop-drilling — same pattern
    // the app already uses for 'enstudio:new-project'.
    const onOpenEvent = () => openPalette()
    window.addEventListener('keydown', onKey, true)
    window.addEventListener('enstudio:canvas-search', onOpenEvent)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      window.removeEventListener('enstudio:canvas-search', onOpenEvent)
    }
  }, [open, openPalette])

  // Focus the input on open; restore prior focus on close.
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 0)
      return () => clearTimeout(t)
    }
    restoreFocusRef.current?.focus?.()
    restoreFocusRef.current = null
  }, [open])

  const close = useCallback(() => setOpen(false), [])

  // Only compute the item list while the palette is open — otherwise this
  // O(n) map re-ran on every `nodes` change (e.g. every frame of a drag) for
  // a component that's rendering nothing. Gating it keeps closed-state free.
  const items = useMemo<Item[]>(() => {
    if (!open) return []
    return nodes
      .filter(n => n.type !== 'pidbg' && (n.data as CData).kind !== 'junction')
      .map(n => {
        const d = n.data as CData
        return { id: n.id, label: String(d.label ?? n.id), kind: String(d.type ?? d.kind ?? '') }
      })
  }, [nodes, open])

  const results = useMemo(() => {
    const s = q.trim().toLowerCase()
    const base = s
      ? items.filter(i => i.label.toLowerCase().includes(s) || i.kind.toLowerCase().includes(s))
      : items
    return base.slice(0, 40)
  }, [items, q])

  if (!open) return null

  const pick = (i: Item) => { onPick(i.id); close() }

  return (
    <div
      className="cvs-search-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Canvas search"
      onKeyDown={e => {
        // Simple focus trap: keep Tab inside the palette; arrows drive the list.
        if (e.key === 'Tab') { e.preventDefault(); inputRef.current?.focus() }
      }}
      onClick={e => { if (e.target === e.currentTarget) close() }}
    >
      <div className="cvs-search">
        <div className="cvs-search__bar">
          <Search size={15} className="cvs-search__icon" aria-hidden="true" />
          <input
            ref={inputRef}
            value={q}
            role="combobox"
            aria-expanded="true"
            aria-controls="cvs-search-list"
            aria-label="Search canvas nodes by tag, equipment or instrument"
            placeholder="Search tags, equipment, instruments…"
            onChange={e => { setQ(e.target.value); setActive(0) }}
            onKeyDown={e => {
              if (e.key === 'Escape') close()
              else if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, results.length - 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
              else if (e.key === 'Enter' && results[active]) pick(results[active])
            }}
          />
          <button className="cvs-search__close" onClick={close} aria-label="Close search"><X size={14} /></button>
        </div>
        <div className="cvs-search__list" id="cvs-search-list" role="listbox" aria-label="Search results">
          {results.length === 0 ? (
            <div className="cvs-search__empty">No matching items</div>
          ) : results.map((i, idx) => (
            <button
              key={i.id}
              role="option"
              aria-selected={idx === active}
              className={`cvs-search__row${idx === active ? ' active' : ''}`}
              onMouseEnter={() => setActive(idx)}
              onClick={() => pick(i)}
            >
              <span className="cvs-search__name">{i.label}</span>
              <span className="cvs-search__kind">{i.kind.replace(/_/g, ' ')}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

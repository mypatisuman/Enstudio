import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import type { Node } from '@xyflow/react';
import type { CData } from '../types';

type Item = { id: string; label: string; kind: string };

export function CanvasSearch({ nodes, onPick }: {
  nodes: Node<CData>[];
  onPick: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const openPalette = useCallback(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement;
    setQ('');
    setActive(0);
    setOpen(true);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) return;
      const el = e.target as HTMLElement | null;
      const typingElsewhere = !!el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && !el.closest('.cvs-search-box');
      if (typingElsewhere && !open) return;
      e.preventDefault();
      if (open) setOpen(false); else openPalette();
    };

    const onOpenEvent = () => openPalette();
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('engenie:canvas-search', onOpenEvent);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('engenie:canvas-search', onOpenEvent);
    };
  }, [open, openPalette]);

  useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
    restoreFocusRef.current?.focus?.();
    restoreFocusRef.current = null;
  }, [open]);

  const close = useCallback(() => setOpen(false), []);

  const items = useMemo<Item[]>(() => {
    if (!open) return [];
    return nodes
      .filter(n => n.type !== 'pidbg' && (n.data as CData).kind !== 'junction')
      .map(n => {
        const d = n.data as CData;
        return { id: n.id, label: String(d.label ?? n.id), kind: String(d.type ?? d.kind ?? '') };
      });
  }, [nodes, open]);

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    const base = s
      ? items.filter(i => i.label.toLowerCase().includes(s) || i.kind.toLowerCase().includes(s))
      : items;
    return base.slice(0, 40);
  }, [items, q]);

  if (!open) return null;

  const pick = (i: Item) => { onPick(i.id); close(); };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4 bg-slate-950/60 backdrop-blur-sm animate-in fade-in duration-150"
      role="dialog"
      aria-modal="true"
      aria-label="Canvas search"
      onClick={e => { if (e.target === e.currentTarget) close(); }}
    >
      <div className="cvs-search-box w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl overflow-hidden flex flex-col animate-in zoom-in-95 duration-200">
        <div className="flex items-center px-4 py-3 border-b border-slate-800 gap-3">
          <Search className="h-5 w-5 text-slate-400 shrink-0" />
          <input
            ref={inputRef}
            value={q}
            placeholder="Search tags, valves, transmitters, vessels... (ESC to close)"
            onChange={e => { setQ(e.target.value); setActive(0); }}
            onKeyDown={e => {
              if (e.key === 'Escape') close();
              else if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, results.length - 1)); }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
              else if (e.key === 'Enter' && results[active]) pick(results[active]);
            }}
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-500 outline-none"
          />
          <button onClick={close} className="p-1 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-80 overflow-y-auto p-2 space-y-1 custom-visible-scrollbar-dark">
          {results.length === 0 ? (
            <div className="p-6 text-center text-sm text-slate-400">
              No matching P&ID components found
            </div>
          ) : (
            results.map((item, idx) => (
              <button
                key={item.id}
                onClick={() => pick(item)}
                onMouseEnter={() => setActive(idx)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-left text-sm transition-colors ${
                  idx === active ? 'bg-sky-500/20 text-white' : 'text-slate-300 hover:bg-slate-800/60'
                }`}
              >
                <span className="font-semibold">{item.label}</span>
                <span className="text-xs text-slate-400 uppercase tracking-wider font-mono">
                  {item.kind.replace(/_/g, ' ')}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

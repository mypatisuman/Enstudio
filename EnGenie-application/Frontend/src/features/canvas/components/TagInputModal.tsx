import React, { useState, useRef, useEffect } from 'react';
import * as graphService from '../../../services/pidGraphService';
import { TAG_PREFIXES } from '../../../domain/isa/classification';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function TagInputModal({ kind, sessionId, onDone, onCancel }: {
  kind: string;
  sessionId: string;
  onDone: (tag: string, nodeId: string) => void;
  onCancel: () => void;
}) {
  const [tag, setTag] = useState(TAG_PREFIXES[kind] ?? '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
    ref.current?.setSelectionRange(tag.length, tag.length);
  }, []);

  async function confirm() {
    const t = tag.trim();
    if (!t) { setErr('Enter a tag name'); return; }
    setBusy(true);
    setErr('');
    try {
      const result = await graphService.batchInsertNodes(
        sessionId, JSON.stringify([{ tag: t, kind, area: '', description: '' }])
      );
      if (!result.ids.length) { setErr('Tag already exists'); setBusy(false); return; }
      onDone(t, result.ids[0].id);
    } catch (e: unknown) {
      setErr(typeof e === 'string' ? e : String(e));
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={e => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl p-5 w-80 shadow-2xl flex flex-col gap-4 animate-in zoom-in-95 duration-200">
        <div className="font-bold text-sm text-slate-100">
          Add {kind.replace(/_/g, ' ')}
        </div>
        <div>
          <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
            Component Tag Name
          </label>
          <Input
            ref={ref}
            type="text"
            value={tag}
            placeholder="e.g. PT-101, V-102"
            onChange={e => { setTag(e.target.value); setErr(''); }}
            onKeyDown={e => {
              if (e.key === 'Enter') confirm();
              if (e.key === 'Escape') onCancel();
            }}
            className="bg-slate-800 border-slate-700 text-sm h-9 text-slate-100"
          />
          {err && <div className="text-xs text-rose-400 mt-1.5">{err}</div>}
        </div>
        <div className="flex gap-2 justify-end pt-2">
          <Button variant="ghost" size="sm" onClick={onCancel} className="text-xs h-8 text-slate-400 hover:text-white">
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!tag.trim() || busy}
            onClick={confirm}
            className="bg-sky-600 hover:bg-sky-500 text-white text-xs h-8 font-medium"
          >
            {busy ? 'Adding...' : 'Add Component →'}
          </Button>
        </div>
      </div>
    </div>
  );
}

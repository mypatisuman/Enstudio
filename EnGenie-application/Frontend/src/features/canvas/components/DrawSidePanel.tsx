import React, { useState, useEffect } from 'react';
import * as graphService from '../../../services/pidGraphService';
import * as canvasService from '../../../services/pidCanvasService';
import { isInstrument } from '../../../domain/isa/instrument';
import type { CData } from '../types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { X, Trash2, Check } from 'lucide-react';

export function DrawSidePanel({
  node,
  open,
  sessionId,
  isExtracted,
  onClose,
  onSave,
  onDelete,
}: {
  node: CData;
  open: boolean;
  sessionId: string;
  isExtracted?: boolean;
  onClose: () => void;
  onSave: (updated: CData) => void;
  onDelete: () => void;
}) {
  if (!open) return null;

  const nodeId = String((node as Record<string, unknown>).nodeId ?? (node as Record<string, unknown>).id ?? '');
  const [tag, setTag] = useState(String(node.label));
  const [kind, setKind] = useState(String(node.type || node.kind));
  const [category, setCategory] = useState(isInstrument(String(node.kind)) ? 'Instrument' : 'Equipment');
  const [area, setArea] = useState(String(node.area ?? ''));
  const [equipmentRef, setEquipmentRef] = useState(String(node.equipment_ref ?? ''));

  const [dbKinds, setDbKinds] = useState<{ instruments: string[]; equipment: string[] }>({
    instruments: [],
    equipment: [],
  });
  useEffect(() => {
    canvasService.getNodeKinds().then(setDbKinds).catch(console.error);
  }, []);

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState('');

  async function save() {
    if (!nodeId || !tag.trim()) { setErr('Tag cannot be empty'); return; }
    setSaving(true);
    setErr('');
    try {
      await graphService.updateNode(sessionId, nodeId, tag.trim(), kind, area, '');
      onSave({
        ...node,
        label: tag.trim(),
        kind,
        kind_detail: kind,
        area,
        equipment_ref: equipmentRef.trim(),
      });
      onClose();
    } catch (e: unknown) {
      setErr(typeof e === 'string' ? e : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function del() {
    if (!nodeId) return;
    if (!window.confirm(`Delete ${String(node.label)}?`)) return;
    setDeleting(true);
    try {
      await graphService.deleteNode(sessionId, nodeId);
      onDelete();
      onClose();
    } catch (e: unknown) {
      setErr(typeof e === 'string' ? e : String(e));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="w-72 shrink-0 border-l border-slate-800 bg-slate-900/95 backdrop-blur-xl p-4 flex flex-col gap-4 overflow-y-auto custom-visible-scrollbar-dark z-20">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
        <span className="font-bold text-sm text-slate-100">Edit Node</span>
        <button
          onClick={onClose}
          className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-3">
        <div>
          <Label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
            Tag {isExtracted ? '(Read-only)' : ''}
          </Label>
          <Input
            value={tag}
            onChange={e => { setTag(e.target.value); setErr(''); }}
            disabled={isExtracted}
            className="mt-1 bg-slate-800/80 border-slate-700 text-xs h-8"
          />
        </div>

        <div>
          <Label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Category</Label>
          <select
            value={category}
            onChange={e => setCategory(e.target.value)}
            className="mt-1 w-full bg-slate-800/80 border border-slate-700 text-slate-100 rounded-md px-2 h-8 text-xs outline-none"
          >
            <option value="Instrument">Instrument</option>
            <option value="Equipment">Process Equipment</option>
          </select>
        </div>

        <div>
          <Label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Component Type</Label>
          <Input
            value={kind}
            onChange={e => setKind(e.target.value)}
            className="mt-1 bg-slate-800/80 border-slate-700 text-xs h-8"
          />
        </div>

        <div>
          <Label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Area / Train</Label>
          <Input
            value={area}
            onChange={e => setArea(e.target.value)}
            className="mt-1 bg-slate-800/80 border-slate-700 text-xs h-8"
          />
        </div>

        <div>
          <Label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Parent Equipment Ref</Label>
          <Input
            value={equipmentRef}
            onChange={e => setEquipmentRef(e.target.value)}
            placeholder="e.g. C-101 or V-102"
            className="mt-1 bg-slate-800/80 border-slate-700 text-xs h-8"
          />
        </div>

        {err && <div className="text-xs text-rose-400 mt-1">{err}</div>}

        <div className="flex items-center gap-2 pt-3 border-t border-slate-800">
          <Button
            size="sm"
            onClick={save}
            disabled={saving}
            className="flex-1 bg-sky-600 hover:bg-sky-500 text-white text-xs h-8 font-medium gap-1.5"
          >
            <Check className="h-3.5 w-3.5" />
            <span>Save</span>
          </Button>
          <Button
            size="sm"
            variant="destructive"
            onClick={del}
            disabled={deleting}
            className="h-8 px-2.5"
            title="Delete node"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

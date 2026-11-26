import React from 'react';
import { X, Edit3, Tag, Layers, Cpu, Compass, Wrench, Sparkles, Loader2, CheckCircle2 } from 'lucide-react';
import { instrColors, equipColors } from '../../../components/canvas/ISANodes';
import { isInstrument } from '../../../domain/isa/instrument';
import type { CData } from '../types';

function Field({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
        {label}
      </div>
      <div className="text-xs font-medium" style={{ color: color || '#e2e8f0' }}>
        {value}
      </div>
    </div>
  );
}

export interface NodeConnection {
  other: string;
  kind: string;
  label?: string;
  outgoing: boolean;
}

/** How the digitiser obtained a symbol; anything but a plain read needs a look. */
export function provenanceOf(node: Record<string, any>): { text: string; tone: string } | null {
  if (node.inferred) return { text: 'Inferred from loop and annotation - please confirm', tone: 'amber' };
  if (node.recovered) return { text: 'Tag recovered from its printed lettering - please confirm', tone: 'amber' };
  if (node.untagged) return { text: 'Untagged symbol - no tag printed', tone: 'slate' };
  if (node.placeholder) return { text: 'Template placeholder tag', tone: 'slate' };
  if (node.source === 'brownfield_vision') return { text: 'Read from the drawing', tone: 'emerald' };
  return null;
}

const TONE: Record<string, string> = {
  amber: 'bg-amber-500/10 border-amber-500/40 text-amber-300',
  slate: 'bg-slate-500/10 border-slate-500/40 text-slate-300',
  emerald: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300',
};

export function SidePanel({
  node,
  sessionId,
  open,
  onClose,
  onEdit,
  onIdentifyAccessories,
  inferringAccessories = false,
  connections = [],
}: {
  node: CData;
  sessionId?: string;
  open: boolean;
  onClose: () => void;
  onEdit: () => void;
  onIdentifyAccessories?: (tag: string) => void;
  inferringAccessories?: boolean;
  connections?: NodeConnection[];
}) {
  if (!open) return null;

  const instr = isInstrument(String(node.kind));
  const color = instr ? instrColors(String(node.label)).border : equipColors(String(node.kind)).border;
  const soft = node.softChildren ?? [];

  const rawNode = node as any;
  const accessories: any[] = rawNode.accessories || rawNode.extra_json?.accessories || [];
  const specifications: Record<string, any> = rawNode.specifications || rawNode.extra_json?.specifications || {};
  const provenance = provenanceOf(rawNode);
  const fromDrawing = rawNode.source === 'brownfield_vision';

  return (
    <div className="w-80 shrink-0 border-l border-slate-800 bg-slate-900/95 backdrop-blur-xl p-4 flex flex-col gap-4 overflow-y-auto custom-visible-scrollbar-dark z-20">
      {/* Header */}
      <div className="flex items-center gap-2.5 pb-2 border-b border-slate-800">
        <span
          className="w-3 h-3 flex-shrink-0"
          style={{
            borderRadius: instr ? '50%' : '3px',
            border: `2px solid ${color}`,
          }}
        />
        <span className="font-bold text-sm text-slate-100 flex-1 truncate">{String(node.label)}</span>
        <button
          onClick={onEdit}
          className="p-1 rounded text-sky-400 hover:text-sky-300 hover:bg-sky-500/10 transition-colors"
          title="Edit properties"
        >
          <Edit3 className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onClose}
          className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {provenance && (
        <div className={`px-2.5 py-1.5 rounded-lg border text-[11px] font-medium ${TONE[provenance.tone]}`}>
          {provenance.text}
          {fromDrawing && !rawNode.inferred && !rawNode.untagged && (
            <span className="block text-[10px] font-normal opacity-80">
              {rawNode.snapped ? 'Position: exact (on its printed text)' : 'Position: estimated'}
            </span>
          )}
        </div>
      )}

      {/* Fields */}
      <div className="space-y-3">
        <Field label="Category" value={instr ? 'Instrument' : 'Process Equipment'} color={color} />
        {(node.type || node.kind) && (
          <Field label="Component Type" value={String(node.type || node.kind).replace(/_/g, ' ')} />
        )}
        {node.kind_detail && node.kind_detail !== node.kind && (
          <Field label="Detail" value={String(node.kind_detail).replace(/_/g, ' ')} />
        )}
        {node.equipment_ref && <Field label="Equipment Ref" value={String(node.equipment_ref)} />}
        {rawNode.loop && <Field label="Loop" value={String(rawNode.loop)} />}
        {node.area && <Field label="Area / Train" value={String(node.area)} />}
        {rawNode.description && <Field label="Notes on the drawing" value={String(rawNode.description)} />}
        {node.drawing && <Field label="Drawing" value={String(node.drawing)} />}

        {connections.length > 0 && (
          <div className="pt-2 border-t border-slate-800 space-y-1.5">
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              Connections ({connections.length})
            </div>
            <div className="space-y-1">
              {connections.map((c, i) => (
                <div key={i} className="flex items-center gap-2 text-[11px] text-slate-300">
                  <span className="text-slate-500 w-3">{c.outgoing ? '→' : '←'}</span>
                  <span className="font-mono text-slate-100 flex-1 truncate">{c.other}</span>
                  <span className="text-[9px] uppercase tracking-wide text-slate-400">{c.kind}</span>
                  {c.label && <span className="font-mono text-[10px] text-amber-300 truncate max-w-[7rem]">{c.label}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Specifications */}
        {Object.keys(specifications).length > 0 && (
          <div className="pt-2 border-t border-slate-800 space-y-1.5">
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              Engineering Specifications
            </div>
            <div className="p-2 rounded-lg bg-slate-950/60 border border-slate-800 text-[11px] space-y-1">
              {Object.entries(specifications).map(([k, v]) => (
                <div key={k} className="flex justify-between items-center text-slate-300">
                  <span className="text-slate-400 capitalize">{k.replace(/_/g, ' ')}:</span>
                  <span className="font-mono text-slate-100">{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Identified Accessories from Solution Agent */}
        {accessories.length > 0 && (
          <div className="pt-2 border-t border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-[10px] font-bold text-amber-400 uppercase tracking-wider">
                <Wrench className="h-3 w-3" />
                Accessories ({accessories.length})
              </span>
              <span className="text-[9px] text-emerald-400 font-semibold flex items-center gap-0.5">
                <CheckCircle2 size={10} /> Paired
              </span>
            </div>
            <div className="space-y-1.5">
              {accessories.map((acc: any, idx: number) => (
                <div
                  key={idx}
                  className="p-2 rounded-lg bg-slate-800/80 border border-slate-700/60 text-[11px] space-y-0.5"
                >
                  <div className="font-semibold text-slate-100 flex items-center justify-between">
                    <span>{acc.productName || acc.name || acc.category}</span>
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono">
                      {acc.mandatory !== false ? 'Required' : 'Optional'}
                    </span>
                  </div>
                  {acc.description && (
                    <p className="text-[10px] text-slate-400 leading-tight">
                      {acc.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Action: Identify accessories if none found for instrument */}
        {instr && accessories.length === 0 && onIdentifyAccessories && (
          <div className="pt-2 border-t border-slate-800">
            <button
              type="button"
              onClick={() => onIdentifyAccessories(String(node.label || node.id))}
              disabled={inferringAccessories}
              className="w-full flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/40 text-amber-300 text-xs font-semibold transition-all shadow-xs"
            >
              {inferringAccessories ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Inferring Accessories...
                </>
              ) : (
                <>
                  <Sparkles className="h-3.5 w-3.5 text-amber-400" />
                  Identify Accessories (Solution Agent)
                </>
              )}
            </button>
          </div>
        )}

        {/* Soft children (alarms, switches) */}
        {soft.length > 0 && (
          <div className="pt-2 border-t border-slate-800 space-y-2">
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              Alarm / Switch Tags ({soft.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {soft.map(c => {
                const cc = instrColors(c.label);
                return (
                  <span
                    key={c.id}
                    title={c.kind}
                    className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border"
                    style={{
                      borderColor: `${cc.border}66`,
                      backgroundColor: cc.bg,
                      color: cc.text,
                    }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: cc.border }} />
                    {c.label}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

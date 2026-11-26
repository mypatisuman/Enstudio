import React from 'react';
import { instrColors, equipColors } from '../../../components/canvas/ISANodes';
import { isInstrument } from '../../../domain/isa/instrument';
import type { GraphNode, CData } from '../types';

export function OrphanStrip({
  nodes = [],
  selected = null,
  onSelect,
}: {
  nodes?: GraphNode[];
  selected?: CData | null;
  onSelect?: (n: GraphNode) => void;
}) {
  if (!nodes || !nodes.length) return null;
  return (
    <div className="shrink-0 border-t border-slate-800 bg-slate-900/90 px-4 py-2 flex items-center overflow-x-auto gap-2 backdrop-blur-md z-10">
      <span className="text-[10px] font-bold text-slate-400 tracking-wider uppercase mr-2 whitespace-nowrap">
        Unlinked ({nodes.length})
      </span>
      <div className="flex flex-wrap items-center gap-1.5 overflow-x-auto">
        {nodes.map(n => {
          const instr = isInstrument(n.type ?? n.kind);
          const color = instr ? instrColors(n.label).border : equipColors(n.type ?? n.kind).border;
          const isSel = selected?.label === n.label;
          return (
            <button
              key={n.id}
              onClick={() => onSelect(n)}
              title={`${n.kind}${n.area ? ' · ' + n.area : ''}`}
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold transition-all border ${
                isSel
                  ? 'bg-sky-500/20 text-sky-200 border-sky-400'
                  : 'bg-slate-800/80 text-slate-300 hover:text-white border-slate-700 hover:border-slate-600'
              }`}
            >
              <span
                className="w-1.5 h-1.5 flex-shrink-0"
                style={{ borderRadius: instr ? '50%' : '2px', backgroundColor: color }}
              />
              <span>{n.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

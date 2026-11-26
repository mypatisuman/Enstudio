import React, { useState } from 'react';
import { Info } from 'lucide-react';

const ALL_LINE_TYPES = [
  { kinds: ['process', 'stream'], name: 'Process (Main pipe)', stroke: '#ffffff', dash: '' },
  { kinds: ['signal'], name: 'Signal (Electrical)', stroke: '#3b82f6', dash: '6 3' },
  { kinds: ['impulse'], name: 'Impulse (Instrument tap)', stroke: '#22d3ee', dash: '1 3' },
  { kinds: ['pneumatic'], name: 'Pneumatic', stroke: '#38bdf8', dash: '4 3' },
  { kinds: ['bypass'], name: 'Bypass', stroke: '#f59e0b', dash: '5 3' },
  { kinds: ['recycle'], name: 'Recycle', stroke: '#22c55e', dash: '5 3' },
  { kinds: ['hydraulic'], name: 'Hydraulic', stroke: '#a78bfa', dash: '5 2' },
  { kinds: ['utility'], name: 'Utility', stroke: '#0d9488', dash: '2 2' },
  { kinds: ['cross-drawing'], name: 'Cross-drawing', stroke: '#7c3aed', dash: '6 4' },
  { kinds: ['assoc'], name: 'Association', stroke: '#334155', dash: '3 2' },
];

export const LineLegend = ({ presentKinds, open = false }: {
  presentKinds?: Set<string>;
  /** keep the list shown (the canvas toolbar's Legend toggle) instead of on hover */
  open?: boolean;
}) => {
  const [hover, setHover] = useState(false);
  const show = open || hover;
  const visibleLines = presentKinds && presentKinds.size > 0
    ? ALL_LINE_TYPES.filter(l => l.kinds.some(k => presentKinds.has(k)))
    : ALL_LINE_TYPES;
  if (visibleLines.length === 0) return null;

  return (
    <div
      className="relative flex items-center z-30"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <button
        className="h-8 w-8 rounded-md flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
        title="P&ID Line Types Legend"
      >
        <Info className="h-4 w-4" />
      </button>
      {show && (
        <div className="absolute top-full right-0 mt-2 p-3 rounded-xl bg-slate-900/95 border border-slate-700/80 shadow-2xl backdrop-blur-xl w-60 flex flex-col gap-2.5 z-50">
          <div className="text-xs font-bold text-slate-200 border-b border-slate-800 pb-1.5">
            P&ID Line Types
          </div>
          {visibleLines.map(l => (
            <div key={l.name} className="flex items-center gap-2.5">
              <svg width="40" height="4" overflow="visible" className="flex-shrink-0">
                <line x1="0" y1="2" x2="40" y2="2" stroke={l.stroke} strokeWidth="2" strokeDasharray={l.dash} />
              </svg>
              <span className="text-xs text-slate-300 font-medium truncate">{l.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

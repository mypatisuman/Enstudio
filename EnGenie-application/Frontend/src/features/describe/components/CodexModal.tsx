import React from 'react';
import { BookOpen, X, Code2, Tag, ShieldCheck } from 'lucide-react';

interface CodexModalProps {
  open: boolean;
  onClose: () => void;
  onSelectTag?: (tagQuery: string) => void;
}

const TAG_LETTERS = [
  { letter: 'F', first: 'Flow Rate', modifier: 'Ratio / Fraction', readout: 'Indicator (FI)', output: 'Control (FC)' },
  { letter: 'P', first: 'Pressure / Vacuum', modifier: 'Differential (PD)', readout: 'Indicator (PI)', output: 'Switch / Alarm (PSH/PSL)' },
  { letter: 'T', first: 'Temperature', modifier: 'Differential (TD)', readout: 'Indicator (TI)', output: 'Transmitter (TT)' },
  { letter: 'L', first: 'Level', modifier: 'Differential (LD)', readout: 'Glass / Gauge (LG)', output: 'Controller (LC)' },
  { letter: 'A', first: 'Analysis', modifier: '-', readout: 'Indicator (AI)', output: 'Transmitter (AT)' },
  { letter: 'V', first: 'Vibration', modifier: '-', readout: 'Indicator (VI)', output: 'Valve (FV/PV/TV/LV)' },
];

const COMMON_SYMBOLS = [
  { tag: 'V-101', type: 'Pressure Vessel', desc: 'Vertical or horizontal process separator with 2:1 elliptical heads' },
  { tag: 'P-101A/B', type: 'Centrifugal Pump', desc: 'Motor-driven process pump with ANSI / ISO suction and discharge nozzles' },
  { tag: 'E-101', type: 'Shell & Tube Exchanger', desc: 'TEMA type heat exchanger with channel and floating head' },
  { tag: 'CV-101', type: 'Control Valve', desc: 'Pneumatic diaphragm actuated globe valve with fail-safe position' },
  { tag: 'PSV-101', type: 'Pressure Safety Valve', desc: 'Spring-loaded overpressure relief valve discharging to flare header' },
];

export function CodexModal({ open, onClose, onSelectTag }: CodexModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-3xl rounded-2xl bg-[#1e1e1e] border border-white/10 shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#252525]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Code2 size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                ISA-5.1 Engineering Codex
                <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-mono">
                  Standards Reference
                </span>
              </h3>
              <p className="text-xs text-zinc-400">
                Instrumentation symbols, identification letter codes, and standard piping conventions.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Section 1: First Letter Table */}
          <div className="space-y-3">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-2">
              <Tag size={13} className="text-emerald-400" />
              Standard Identification Letter Codes
            </h4>
            <div className="rounded-xl border border-white/10 overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-[#282828] text-zinc-300 border-b border-white/10">
                  <tr>
                    <th className="px-4 py-2.5 font-semibold">Letter</th>
                    <th className="px-4 py-2.5 font-semibold">Measured Variable</th>
                    <th className="px-4 py-2.5 font-semibold">Modifier</th>
                    <th className="px-4 py-2.5 font-semibold">Readout / Passive</th>
                    <th className="px-4 py-2.5 font-semibold">Output / Active</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5 bg-[#202020] text-zinc-300 font-mono">
                  {TAG_LETTERS.map(row => (
                    <tr key={row.letter} className="hover:bg-white/5">
                      <td className="px-4 py-2 font-bold text-emerald-400">{row.letter}</td>
                      <td className="px-4 py-2 font-sans">{row.first}</td>
                      <td className="px-4 py-2">{row.modifier}</td>
                      <td className="px-4 py-2">{row.readout}</td>
                      <td className="px-4 py-2">{row.output}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Section 2: Common Equipment Block Conventions */}
          <div className="space-y-3">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-2">
              <ShieldCheck size={13} className="text-sky-400" />
              Common P&ID Equipment Conventions
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {COMMON_SYMBOLS.map(sym => (
                <div
                  key={sym.tag}
                  onClick={() => {
                    onSelectTag?.(`Describe the engineering specifications for ${sym.tag} (${sym.type})`);
                    onClose();
                  }}
                  className="p-3 rounded-xl bg-[#282828] border border-white/5 hover:border-sky-500/40 cursor-pointer transition-all space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-sky-400">{sym.tag}</span>
                    <span className="text-[11px] text-zinc-400">{sym.type}</span>
                  </div>
                  <p className="text-[11px] text-zinc-400 leading-relaxed">{sym.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-white/10 bg-[#252525] flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-xs font-medium text-white transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

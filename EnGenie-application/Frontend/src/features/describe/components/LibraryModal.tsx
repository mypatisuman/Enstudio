import React from 'react';
import { BookOpen, X, Sparkles, Folder, FileText } from 'lucide-react';

interface LibraryModalProps {
  open: boolean;
  onClose: () => void;
  onSelectTemplate?: (prompt: string) => void;
}

const TEMPLATES = [
  {
    title: 'Separator Drum & Booster Pump Train',
    category: 'Oil & Gas Production',
    desc: '3-phase vertical production separator with boot, level transmitters (LT-101), pressure control valve (PCV-101), and dual centrifugal booster pumps (P-101A/B).',
    prompt: 'Load template: 3-phase production separator V-101 with boot and dual centrifugal booster pumps P-101A/B with discharge check valves and flow transmitter FT-101',
  },
  {
    title: 'Atmospheric Distillation Column System',
    category: 'Petroleum Refining',
    desc: 'Fractionation column T-101 with overhead condenser E-101, reflux accumulator V-102, bottoms reboiler E-102, and reflux pumps P-102A/B.',
    prompt: 'Load template: Atmospheric distillation column T-101 with overhead air cooler E-101, reflux drum V-102, and bottoms reboiler E-102 with temperature control loop',
  },
  {
    title: 'Shell & Tube Heat Exchanger Cascade',
    category: 'Heat Transfer',
    desc: 'Dual shell-and-tube exchangers E-101/102 in series with bypass control valve TV-101, temperature indicators (TI-101..104), and high-temp shutdown switch.',
    prompt: 'Load template: Shell and tube heat exchanger cascade E-101/102 in series with 3-way temperature bypass control valve TV-101',
  },
  {
    title: 'Chemical Metering Skid with Safety Relief',
    category: 'Chemical Ingestion',
    desc: 'Storage tank TK-101, calibration column CC-101, positive displacement diaphragm metering pump P-105, pulsation dampener, and safety relief valve PSV-105.',
    prompt: 'Load template: Chemical metering injection skid with tank TK-101, calibration column CC-101, metering pump P-105, and relief valve PSV-105 discharging to suction',
  },
];

export function LibraryModal({ open, onClose, onSelectTemplate }: LibraryModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-3xl rounded-2xl bg-[#1e1e1e] border border-white/10 shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#252525]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400">
              <BookOpen size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                P&ID Template Library
                <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 font-mono">
                  Standard Process Packages
                </span>
              </h3>
              <p className="text-xs text-zinc-400">
                Industry-proven process flow diagrams and equipment train templates ready to author or customize.
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
        <div className="p-6 overflow-y-auto space-y-3">
          {TEMPLATES.map((tmpl, idx) => (
            <div
              key={idx}
              className="p-4 rounded-xl bg-[#2a2a2a] border border-white/5 hover:border-purple-500/30 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
            >
              <div className="space-y-1.5 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm text-zinc-100">{tmpl.title}</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full border border-purple-500/30 bg-purple-500/10 text-purple-300">
                    {tmpl.category}
                  </span>
                </div>
                <p className="text-xs text-zinc-400 leading-relaxed">{tmpl.desc}</p>
              </div>

              <button
                type="button"
                onClick={() => {
                  onSelectTemplate?.(tmpl.prompt);
                  onClose();
                }}
                className="self-start md:self-center px-3.5 py-1.5 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-200 border border-purple-500/40 text-xs font-medium transition-all flex items-center gap-1.5 flex-shrink-0"
              >
                <Sparkles size={12} className="text-purple-300" />
                <span>Load Template</span>
              </button>
            </div>
          ))}
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

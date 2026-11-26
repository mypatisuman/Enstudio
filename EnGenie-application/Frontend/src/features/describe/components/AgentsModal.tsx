import React from 'react';
import { Bot, Sparkles, X, Layers, Cpu, CheckCircle2 } from 'lucide-react';

interface AgentsModalProps {
  open: boolean;
  onClose: () => void;
  onSelectAgentPrompt?: (prompt: string) => void;
}

const AGENTS = [
  {
    name: 'Greenfield Specialist',
    code: 'greenfield',
    role: 'Builds complete end-to-end P&ID diagrams from raw process requirements or PFD specs.',
    color: 'emerald',
    badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    prompt: 'Design a greenfield sour gas sweetening unit with amine contactor and flash drum',
  },
  {
    name: 'Brownfield Specialist',
    code: 'brownfield',
    role: 'Safely modifies existing operating facilities, respects existing tags and tie-in points.',
    color: 'amber',
    badge: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    prompt: 'Add tie-in valve on line 01-1001-P and route to new surge vessel V-103',
  },
  {
    name: 'Authoring Specialist',
    code: 'authoring',
    role: 'Constructs ISA-5.1 vector nodes, equipment blocks, valves, instruments, and connects piping.',
    color: 'blue',
    badge: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    prompt: 'Add horizontal separator drum V-101 with boot and dual magnetic level transmitters LT-101A/B',
  },
  {
    name: 'Update Specialist',
    code: 'update',
    role: 'Modifies attributes, tags, line sizing, ratings, and design conditions on existing components.',
    color: 'cyan',
    badge: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
    prompt: 'Update line 01-1002-P to 6" schedule 40 carbon steel with 300# flange rating',
  },
  {
    name: 'Deletion & Safety Specialist',
    code: 'deletion',
    role: 'Manages safe decommissioning with Human-In-The-Loop confirmation interrupts before node removal.',
    color: 'rose',
    badge: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
    prompt: 'Decommission obsolete bypass valve FV-102 and its redundant bypass piping',
  },
  {
    name: 'Validation & Audit Specialist',
    code: 'validation',
    role: 'Audits diagram connectivity, orphan equipment, missing relief valves, duplicate tags, and loop numbering.',
    color: 'violet',
    badge: 'bg-violet-500/10 text-violet-400 border-violet-500/30',
    prompt: 'Run engineering rule audit for isolated equipment and duplicate ISA tags',
  },
  {
    name: 'Solution Architect Specialist',
    code: 'solution',
    role: 'Formulates multi-phase engineering execution plans and orchestrates downstream agent handoffs.',
    color: 'indigo',
    badge: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',
    prompt: 'Formulate an engineering upgrade plan to convert single pump P-101 into an N+1 standby configuration',
  },
  {
    name: 'Query & Intelligence Specialist',
    code: 'query',
    role: 'Answers technical process queries, explains ISA-5.1 standard nomenclature, and summarizes topology.',
    color: 'slate',
    badge: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
    prompt: 'List all centrifugal pumps and identify their suction and discharge line diameters',
  },
];

export function AgentsModal({ open, onClose, onSelectAgentPrompt }: AgentsModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-3xl rounded-2xl bg-[#1e1e1e] border border-white/10 shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#252525]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400">
              <Cpu size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                P&ID Multi-Agent Swarm
                <span className="text-xs px-2 py-0.5 rounded-full bg-sky-500/20 text-sky-300 font-mono">
                  8 Specialized Agents
                </span>
              </h3>
              <p className="text-xs text-zinc-400">
                Collaborative autonomous engineering agents orchestrated to author, modify, and audit P&IDs.
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

        {/* Agent Cards Grid */}
        <div className="p-6 overflow-y-auto space-y-3">
          {AGENTS.map(agent => (
            <div
              key={agent.code}
              className="p-4 rounded-xl bg-[#2a2a2a] border border-white/5 hover:border-white/20 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
            >
              <div className="space-y-1.5 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm text-zinc-100">{agent.name}</span>
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${agent.badge}`}>
                    @{agent.code}
                  </span>
                </div>
                <p className="text-xs text-zinc-400 leading-relaxed">{agent.role}</p>
              </div>

              <button
                type="button"
                onClick={() => {
                  onSelectAgentPrompt?.(agent.prompt);
                  onClose();
                }}
                className="self-start md:self-center px-3 py-1.5 rounded-lg bg-white/5 hover:bg-sky-500/20 hover:text-sky-300 hover:border-sky-500/40 text-xs font-medium text-zinc-300 border border-white/10 transition-all flex items-center gap-1.5 flex-shrink-0"
              >
                <Sparkles size={12} className="text-sky-400" />
                <span>Try prompt</span>
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

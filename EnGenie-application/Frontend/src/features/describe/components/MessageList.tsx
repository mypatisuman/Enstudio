import React, { useState, type RefObject } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  Sparkles,
  Bot,
  User,
  ChevronDown,
  ChevronRight,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  Layers,
  ArrowRight,
  ExternalLink,
  PlusCircle,
  Brain,
} from 'lucide-react';
import type { ChatEntry } from '../types';
import { MODE_LABELS } from '../answerMeta';

interface MessageListProps {
  chat: ChatEntry[];
  loading: boolean;
  bottomRef: RefObject<HTMLDivElement | null>;
  onCancelDeletes: (entryIndex: number) => void;
  onConfirmDeletes: (entryIndex: number, tags: string[]) => void;
  onFocusTag?: (tag: string) => void;
  onSendPreset?: (text: string) => void;
  onBuildCanvas?: () => void;
}

const AGENT_BADGE_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  greenfield: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/30' },
  brownfield: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/30' },
  authoring: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30' },
  update: { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/30' },
  deletion: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/30' },
  validation: { bg: 'bg-violet-500/10', text: 'text-violet-400', border: 'border-violet-500/30' },
  solution: { bg: 'bg-indigo-500/10', text: 'text-indigo-400', border: 'border-indigo-500/30' },
  query: { bg: 'bg-zinc-500/10', text: 'text-zinc-400', border: 'border-zinc-500/30' },
};

export function MessageList({
  chat,
  loading,
  bottomRef,
  onCancelDeletes,
  onConfirmDeletes,
  onFocusTag,
  onBuildCanvas,
}: MessageListProps) {
  const [expandedReasoning, setExpandedReasoning] = useState<Record<number, boolean>>({});

  const toggleReasoning = (idx: number) => {
    setExpandedReasoning(prev => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 scrollbar-thin scrollbar-thumb-zinc-700">
      <div className="max-w-3xl mx-auto space-y-6">
        {chat.map((entry, idx) => {
          const isUser = entry.role === 'user';
          const agentStyle = entry.agent
            ? AGENT_BADGE_STYLES[entry.agent.toLowerCase()] || AGENT_BADGE_STYLES.query
            : null;
          const isReasoningOpen = !!expandedReasoning[idx];

          return (
            <div
              key={idx}
              className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} space-y-1.5 animate-in fade-in duration-200`}
            >
              {/* Header info */}
              <div className="flex items-center gap-2 px-1 text-[11px] text-zinc-400">
                {isUser ? (
                  <>
                    <span>You</span>
                    <div className="w-5 h-5 rounded-full bg-zinc-700 flex items-center justify-center text-white text-[10px] font-bold">
                      <User size={12} />
                    </div>
                  </>
                ) : (
                  <>
                    <div className="w-5 h-5 rounded-full bg-sky-500/20 border border-sky-500/40 flex items-center justify-center text-sky-400">
                      <Sparkles size={11} />
                    </div>
                    <span className="font-semibold text-zinc-200">Copilot</span>
                    {entry.agent && agentStyle && (
                      <span
                        className={`px-2 py-0.5 rounded-full border text-[10px] font-mono capitalize ${agentStyle.bg} ${agentStyle.text} ${agentStyle.border}`}
                      >
                        @{entry.agent}
                      </span>
                    )}
                    {entry.mode && MODE_LABELS[entry.mode] && (
                      <span
                        className="px-2 py-0.5 rounded-full border border-white/10 bg-white/5 text-[10px] text-zinc-300"
                        title="How your message was read"
                      >
                        {MODE_LABELS[entry.mode]}
                      </span>
                    )}
                  </>
                )}
              </div>

              {/* Message Bubble */}
              <div
                className={`rounded-2xl p-4 text-sm leading-relaxed transition-all shadow-md ${
                  isUser
                    ? 'bg-[#2f2f2f] text-white max-w-[85%] rounded-tr-xs'
                    : entry.isError
                    ? 'bg-rose-950/30 border border-rose-500/40 text-rose-300 w-full rounded-tl-xs'
                    : 'bg-[#212121] border border-white/5 text-zinc-200 w-full rounded-tl-xs'
                }`}
              >
                {/* Optional Reasoning Collapse for assistant */}
                {!isUser && entry.reasoning && (
                  <div className="mb-3 pb-3 border-b border-white/10">
                    <button
                      type="button"
                      onClick={() => toggleReasoning(idx)}
                      className="flex items-center gap-1.5 text-xs font-medium text-sky-400 hover:text-sky-300 transition-colors"
                    >
                      <Brain size={13} />
                      {isReasoningOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      <span>Thinking Process & Deliberation</span>
                    </button>
                    {isReasoningOpen && (
                      <div className="mt-2.5 p-3 rounded-xl bg-[#171717] border border-white/5 font-mono text-xs text-zinc-400 whitespace-pre-wrap leading-relaxed">
                        {entry.reasoning}
                      </div>
                    )}
                  </div>
                )}

                {/* Message Content */}
                {entry.answerMarkdown ? (
                  <div className="prose prose-invert prose-sm max-w-none text-zinc-200 leading-relaxed font-sans">
                    <ReactMarkdown>{entry.display}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap">{entry.display}</p>
                )}

                {/* Build Solution on Canvas Action Card */}
                {!isUser && onBuildCanvas && (entry.display?.toLowerCase()?.includes('build solution on canvas') || entry.display?.toLowerCase()?.includes('build canva')) && (
                  <div className="mt-3.5 p-3 rounded-xl bg-gradient-to-r from-emerald-950/60 via-teal-950/40 to-zinc-900 border border-emerald-500/40 flex items-center justify-between gap-3 shadow-lg">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 flex-shrink-0">
                        <Layers size={16} />
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-white">Engineering Solution Ready</div>
                        <div className="text-[11px] text-zinc-400">Generate and wire complete P&ID diagram on canvas</div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={onBuildCanvas}
                      className="px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-medium text-xs shadow-md transition-all flex items-center gap-1.5 flex-shrink-0 cursor-pointer hover:shadow-emerald-900/40"
                    >
                      <Layers size={13} />
                      <span>Build Solution on Canvas</span>
                    </button>
                  </div>
                )}

                {/* Action summary badges */}
                {!isUser &&
                  (entry.nodesAdded || entry.edgesAdded || entry.nodesUpdated || entry.nodesDeleted) && (
                    <div className="mt-3 pt-3 border-t border-white/10 flex flex-wrap gap-2 text-xs">
                      {entry.nodesAdded && entry.nodesAdded > 0 && (
                        <span className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-mono text-xs">
                          <CheckCircle2 size={12} /> +{entry.nodesAdded} equipment created
                        </span>
                      )}
                      {entry.edgesAdded && entry.edgesAdded > 0 && (
                        <span className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/30 font-mono text-xs">
                          <Layers size={12} /> +{entry.edgesAdded} piping connected
                        </span>
                      )}
                      {entry.nodesUpdated && entry.nodesUpdated > 0 && (
                        <span className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 font-mono text-xs">
                          ~{entry.nodesUpdated} properties modified
                        </span>
                      )}
                      {entry.nodesDeleted && entry.nodesDeleted > 0 && (
                        <span className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/30 font-mono text-xs">
                          -{entry.nodesDeleted} decommissioned
                        </span>
                      )}
                    </div>
                  )}

                {/* Tag references buttons (click to focus canvas) */}
                {!isUser && entry.results && entry.results.length > 0 && (
                  <div className="mt-3 pt-2.5 border-t border-white/10 flex flex-wrap gap-1.5 items-center">
                    <span className="text-[11px] text-zinc-400" title={entry.sources?.length ? `From: ${entry.sources.join(', ')}` : undefined}>
                      {entry.mode === 'question' || entry.mode === 'mixed' ? 'Cited from the drawing:' : 'Referenced Tags:'}
                    </span>
                    {entry.results.map((res, rIdx) => (
                      <button
                        key={rIdx}
                        type="button"
                        onClick={() => onFocusTag?.(res.tag)}
                        className="px-2 py-0.5 rounded-md bg-white/5 hover:bg-sky-500/20 text-sky-400 border border-white/10 text-xs font-mono transition-colors flex items-center gap-1"
                      >
                        <span>{res.tag}</span>
                        <ExternalLink size={10} />
                      </button>
                    ))}
                  </div>
                )}

                {/* HITL Pending Deletes Card */}
                {!isUser && entry.pendingDeletes && entry.pendingDeletes.length > 0 && (
                  <div className="mt-4 p-3.5 rounded-xl border border-rose-500/40 bg-rose-950/20 space-y-2.5">
                    <div className="flex items-center gap-2 text-rose-400 font-semibold text-xs">
                      <AlertTriangle size={15} />
                      <span>Safety Gate: Confirm Deletion</span>
                    </div>
                    <p className="text-xs text-zinc-300">
                      The agent proposed removing the following equipment and associated connections:
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {entry.pendingDeletes.map((tag, tIdx) => (
                        <span
                          key={tIdx}
                          className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-mono text-xs border border-rose-500/30"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>

                    {entry.deleteResolution ? (
                      <div className="pt-1 text-xs font-medium">
                        {entry.deleteResolution === 'confirmed' ? (
                          <span className="text-emerald-400 flex items-center gap-1">
                            <CheckCircle2 size={13} /> Deletion confirmed by engineer.
                          </span>
                        ) : (
                          <span className="text-zinc-400">Deletion cancelled.</span>
                        )}
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => onConfirmDeletes(idx, entry.pendingDeletes!)}
                          className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-medium text-xs transition-colors flex items-center gap-1"
                        >
                          <Trash2 size={12} />
                          <span>Confirm Delete</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => onCancelDeletes(idx)}
                          className="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-zinc-300 text-xs transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Loading Indicator */}
        {loading && (
          <div className="flex items-start gap-2.5 animate-pulse">
            <div className="w-5 h-5 rounded-full bg-sky-500/20 border border-sky-500/40 flex items-center justify-center text-sky-400">
              <Sparkles size={11} className="animate-spin" />
            </div>
            <div className="bg-[#212121] border border-white/5 rounded-2xl rounded-tl-xs p-3.5 text-xs text-zinc-400 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-sky-400 animate-ping" />
              <span>Multi-agent swarm deliberating and drafting solution...</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} className="h-4" />
      </div>
    </div>
  );
}

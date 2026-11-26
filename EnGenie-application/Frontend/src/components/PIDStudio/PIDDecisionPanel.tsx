import React, { useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleDashed, Database, GitBranch, Loader2, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { clarifyPidAction, confirmPidAction } from '@/components/AIRecommender/api';

/**
 * The engineer's side of a persisted P&ID.
 *
 * - A pending decision the retrofit agent left: queued deletions to confirm, or
 *   which subsystem new equipment goes into.
 * - How the drawing was built (the agent's tool loop or the deterministic
 *   builder), its validation score and control-loop status.
 * - Where each node's specifications came from. Nothing is invented, so
 *   "unspecified" is common and expected; the highlight toggle shows where.
 */

// Keys arrive camelCased from the API; values (spec_status, kinds) do not.
export const SPEC_SOURCES: { key: string; camel: string; label: string; tone: string }[] = [
    { key: 'asset_inventory', camel: 'assetInventory', label: 'Assets Table', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
    { key: 'stated', camel: 'stated', label: 'Stated', tone: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
    { key: 'bom_selection', camel: 'bomSelection', label: 'BOM selection', tone: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
    { key: 'unspecified', camel: 'unspecified', label: 'Unspecified', tone: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
];

export const specSourceLabel = (status?: string): string =>
    SPEC_SOURCES.find(s => s.key === status)?.label || 'Unspecified';

const PATH_LABELS: Record<string, string> = {
    tool_loop: 'Built by retrofit agent',
    fallback: 'Deterministic build',
    engineer_confirmed: 'Removal confirmed',
    engineer_cancelled: 'Removal cancelled',
    awaiting_clarification: 'Waiting for your answer',
};

const LOOP_GAPS = new Set(['no_controller', 'no_final_element', 'incomplete']);

interface Props {
    pidGraph: any;
    onGraphUpdated: (graph: any) => void;
    highlightUnspecified: boolean;
    onToggleHighlight: () => void;
}

export default function PIDDecisionPanel({ pidGraph, onGraphUpdated, highlightUnspecified, onToggleHighlight }: Props) {
    const [busy, setBusy] = useState<string | null>(null);
    const [message, setMessage] = useState<{ tone: 'error' | 'info'; text: string } | null>(null);

    const pending = pidGraph?.pendingAction || pidGraph?.pending_action;
    const sessionId: string | undefined = pidGraph?.sessionId || pidGraph?.session_id;
    const revision: number | undefined = pidGraph?.revision;
    const canDecide = Boolean(sessionId && typeof revision === 'number');

    const validation = pidGraph?.validation || {};
    const loops: { loopId?: string; loop_id?: string; status: string }[] = validation.loops || [];
    const loopGaps = loops.filter(l => LOOP_GAPS.has(l.status));
    const counts = pidGraph?.specStatusCounts || pidGraph?.spec_status_counts || {};
    const notes: string[] = pidGraph?.notes || [];
    const path: string | undefined = pidGraph?.generationPath || pidGraph?.generation_path;

    const apply = async (label: string, run: () => ReturnType<typeof confirmPidAction>) => {
        setBusy(label);
        setMessage(null);
        const res = await run();
        setBusy(null);
        if (res.success && res.pidGraph) {
            onGraphUpdated(res.pidGraph);
            return;
        }
        if (res.conflict && res.pidGraph) {
            onGraphUpdated(res.pidGraph);
            setMessage({ tone: 'info', text: 'The P&ID changed since you opened it, so nothing was applied. This is the latest version; decide again if needed.' });
            return;
        }
        setMessage({ tone: 'error', text: res.question ? `${res.error} ${res.question}` : (res.error || 'Something went wrong.') });
    };

    const confirm = (confirmed: boolean) =>
        apply(confirmed ? 'remove' : 'keep', () => confirmPidAction(sessionId!, revision!, confirmed));
    const answer = (value: string, label: string) =>
        apply(label, () => clarifyPidAction(sessionId!, revision!, value));

    return (
        <div className="flex flex-col gap-2 border-b border-slate-800 bg-slate-900/70 px-4 py-2 text-xs shrink-0 z-10">
            {pending && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3" role="alert">
                    <div className="flex items-start gap-2">
                        {pending.kind === 'confirm_delete'
                            ? <Trash2 className="h-4 w-4 text-amber-300 mt-0.5 shrink-0" />
                            : <GitBranch className="h-4 w-4 text-amber-300 mt-0.5 shrink-0" />}
                        <div className="flex-1 min-w-0">
                            <p className="font-semibold text-amber-100">
                                {pending.kind === 'confirm_delete' ? 'Confirm removal' : 'Which subsystem?'}
                            </p>
                            <p className="mt-0.5 text-amber-100/80 whitespace-pre-line">
                                {pending.kind === 'confirm_delete'
                                    ? pending.question
                                    : String(pending.question || '').split('\n')[0]}
                            </p>
                            {pending.kind === 'subsystem_choice' && pending.request && (
                                <p className="mt-1 text-amber-100/60 italic truncate" title={pending.request}>
                                    Request: “{pending.request}”
                                </p>
                            )}

                            {!canDecide ? (
                                <p className="mt-2 text-amber-200/70">
                                    Reopen this P&ID from the solution page to act on it.
                                </p>
                            ) : pending.kind === 'confirm_delete' ? (
                                <div className="mt-2 flex gap-2">
                                    <Button size="sm" variant="destructive" disabled={!!busy} onClick={() => confirm(true)}>
                                        {busy === 'remove' && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                                        Remove {(pending.targets || []).join(', ')}
                                    </Button>
                                    <Button size="sm" variant="outline" disabled={!!busy} onClick={() => confirm(false)}>
                                        {busy === 'keep' && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                                        Keep
                                    </Button>
                                </div>
                            ) : (
                                <>
                                    <div className="mt-2 flex flex-wrap gap-2">
                                        {(pending.candidates || []).map((c: any, i: number) => (
                                            <Button key={c.path || c.name} size="sm" variant="secondary" disabled={!!busy}
                                                onClick={() => answer(String(i + 1), c.name)}>
                                                {busy === c.name && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                                                {c.path || c.name}
                                                {typeof c.nodes === 'number' && <span className="ml-1 opacity-60">({c.nodes})</span>}
                                            </Button>
                                        ))}
                                        <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => answer('none', 'none')}>
                                            {busy === 'none' && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                                            Leave unassigned
                                        </Button>
                                    </div>
                                    {busy && (
                                        <p className="mt-1 text-amber-200/70">Applying the modification; this can take up to a minute.</p>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {message && (
                <p className={message.tone === 'error' ? 'text-red-300' : 'text-sky-300'}>{message.text}</p>
            )}

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                {path && (
                    <span className="flex items-center gap-1 text-slate-300">
                        <CircleDashed className="h-3.5 w-3.5 text-slate-500" />
                        {PATH_LABELS[path] || path}
                        {typeof revision === 'number' && <span className="text-slate-500">· rev {revision}</span>}
                    </span>
                )}
                {typeof validation.score === 'number' && (
                    <span className="flex items-center gap-1 text-slate-300"
                        title={`${validation.orphans ?? 0} unconnected, ${validation.duplicateTags ?? validation.duplicate_tags ?? 0} duplicate tags`}>
                        {validation.score >= 90
                            ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                            : <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />}
                        Drawing check {validation.score}/100
                    </span>
                )}
                {loops.length > 0 && (
                    <span className={loopGaps.length ? 'text-amber-300' : 'text-slate-300'}
                        title={loops.map(l => `Loop ${l.loopId || l.loop_id}: ${l.status.replace(/_/g, ' ')}`).join('\n')}>
                        {loops.length} loop{loops.length === 1 ? '' : 's'}
                        {loopGaps.length > 0 && ` · ${loopGaps.length} need attention`}
                    </span>
                )}

                <span className="flex items-center gap-1.5 ml-auto">
                    <Database className="h-3.5 w-3.5 text-slate-500" />
                    <span className="text-slate-400">Specs:</span>
                    {SPEC_SOURCES.map(s => {
                        const n = counts[s.camel] ?? counts[s.key] ?? 0;
                        return n ? (
                            <Badge key={s.key} variant="outline" className={`px-1.5 py-0 text-[10px] font-medium ${s.tone}`}>
                                {s.label} {n}
                            </Badge>
                        ) : null;
                    })}
                    {(counts.unspecified ?? 0) > 0 && (
                        <button onClick={onToggleHighlight}
                            className={`rounded px-1.5 py-0.5 text-[10px] font-medium border transition-colors ${highlightUnspecified
                                ? 'border-amber-400 bg-amber-500/20 text-amber-200'
                                : 'border-slate-700 text-slate-400 hover:text-slate-200'}`}>
                            {highlightUnspecified ? 'Hide' : 'Show'} unspecified
                        </button>
                    )}
                </span>
            </div>

            {notes.length > 0 && (
                <p className="text-slate-400" title={notes.join('\n')}>
                    Left unchanged: {notes.slice(0, 2).join('; ')}{notes.length > 2 ? ` (+${notes.length - 2} more)` : ''}
                </p>
            )}
        </div>
    );
}

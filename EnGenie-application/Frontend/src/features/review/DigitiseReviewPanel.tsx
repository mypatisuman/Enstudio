import { useCallback, useEffect, useState } from 'react';
import { Check, X, Edit2, Link2, Loader2, ExternalLink, ShieldCheck } from 'lucide-react';
import {
  actionsFor,
  getReviewQueue,
  resolveReviewItem,
  type ReviewAction,
  type ReviewItem,
  type ReviewQueue,
} from '../../services/pidReviewService';
import { requestCanvasFocus } from '../canvas/focusBus';
import { confidenceInfo } from './confidence';

const KIND_LABEL: Record<string, string> = { tag: 'Tag', link: 'Connection', missing: 'Possibly missing' };
const ACTION_LABEL: Record<ReviewAction, string> = {
  confirm: 'Correct as read',
  reject: 'Remove',
  rename: 'Rename',
  add_link: 'Add link',
  remove_link: 'Remove link',
};

interface Props {
  sessionId: string;
  /** called with the updated graph after each decision */
  onGraphChanged?: (graph: any) => void;
}

/** The digitiser's uncertain items, least certain first: the engineer settles each
 *  one and the drawing is corrected immediately. */
export function DigitiseReviewPanel({ sessionId, onGraphChanged }: Props) {
  const [queue, setQueue] = useState<ReviewQueue>({ items: [], counts: {} });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [inputs, setInputs] = useState<Record<string, { value: string; kind?: string }>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setQueue(await getReviewQueue(sessionId));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (item: ReviewItem, action: ReviewAction) => {
    const input = inputs[item.id]?.value?.trim() || '';
    let correction: Record<string, string> | undefined;
    if (action === 'rename') {
      if (!input) return setError(`Type the correct tag for ${item.tags[0]} first.`);
      correction = { tag: input };
    } else if (action === 'add_link') {
      if (!input) return setError(`Type the tag ${item.tags[0]} connects to first.`);
      correction = { from: item.tags[0], to: input, kind: inputs[item.id]?.kind || 'stream' };
    }
    setBusy(item.id);
    try {
      const res = await resolveReviewItem(sessionId, item.id, action, correction);
      setQueue(q => ({
        counts: res.counts || q.counts,
        items: q.items.map(i => (i.id === item.id ? { ...i, status: res.status } : i)),
      }));
      if (res.pid_graph) onGraphChanged?.(res.pid_graph);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const pending = queue.items.filter(i => i.status === 'pending');
  const shown = showDone ? queue.items : pending;

  if (loading) {
    return (
      <div className="p-6 text-xs text-muted-foreground flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Loading the review queue...
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2 text-foreground">
          <ShieldCheck size={15} className={pending.length ? 'text-amber-500' : 'text-emerald-500'} />
          {pending.length
            ? <span><b>{pending.length}</b> item(s) to check before the drawing is final</span>
            : <span className="text-emerald-500 font-semibold">Everything the digitiser was unsure of has been checked.</span>}
          <span className="text-muted-foreground">
            ({queue.counts.confirmed || 0} confirmed, {queue.counts.corrected || 0} corrected, {queue.counts.rejected || 0} removed)
          </span>
        </div>
        <label className="flex items-center gap-1.5 text-muted-foreground cursor-pointer">
          <input type="checkbox" checked={showDone} onChange={e => setShowDone(e.target.checked)} />
          Show checked items
        </label>
      </div>
      {error && <div className="px-3 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs">{error}</div>}

      {shown.map(item => {
        const conf = confidenceInfo(item.confidence);
        const done = item.status !== 'pending';
        return (
          <div key={item.id} className={`p-3 rounded-xl border bg-background text-xs space-y-2 ${done ? 'opacity-60 border-border' : 'border-border'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="px-2 py-0.5 rounded-md border border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                {KIND_LABEL[item.kind] || item.kind}
              </span>
              {item.tags.map(t => (
                <button
                  key={t}
                  type="button"
                  onClick={() => requestCanvasFocus(t)}
                  className="px-2 py-0.5 rounded-md bg-sky-500/10 text-sky-500 border border-sky-500/30 font-mono flex items-center gap-1 hover:bg-sky-500/20"
                  title="Show on the canvas"
                >
                  {t} <ExternalLink size={10} />
                </button>
              ))}
              <span className="ml-auto font-mono" style={{ color: conf.color }} title="How sure the digitiser was">
                {conf.pct}%
              </span>
              {done && <span className="text-emerald-500 font-semibold capitalize">{item.status}</span>}
            </div>
            <p className="text-foreground leading-relaxed">{item.reason}</p>
            {!done && (
              <div className="flex flex-wrap items-center gap-2">
                {(actionsFor(item).includes('rename') || actionsFor(item).includes('add_link')) && (
                  <input
                    value={inputs[item.id]?.value || ''}
                    onChange={e => setInputs(s => ({ ...s, [item.id]: { ...s[item.id], value: e.target.value } }))}
                    placeholder={item.kind === 'tag' ? 'Correct tag' : 'Connects to (tag)'}
                    className="px-2 py-1 rounded-lg border border-border bg-card text-foreground font-mono w-36 outline-none"
                  />
                )}
                {item.kind === 'missing' && (
                  <select
                    value={inputs[item.id]?.kind || 'stream'}
                    onChange={e => setInputs(s => ({ ...s, [item.id]: { ...s[item.id], value: s[item.id]?.value || '', kind: e.target.value } }))}
                    className="px-2 py-1 rounded-lg border border-border bg-card text-foreground outline-none"
                  >
                    <option value="stream">Process line</option>
                    <option value="signal">Signal line</option>
                    <option value="impulse">Impulse line</option>
                  </select>
                )}
                {actionsFor(item).map(a => (
                  <button
                    key={a}
                    type="button"
                    disabled={busy === item.id}
                    onClick={() => act(item, a)}
                    className={`px-2.5 py-1 rounded-lg font-medium flex items-center gap-1 border ${
                      a === 'reject'
                        ? 'border-red-500/40 text-red-500 hover:bg-red-500/10'
                        : a === 'confirm'
                        ? 'border-emerald-500/40 text-emerald-500 hover:bg-emerald-500/10'
                        : 'border-border text-foreground hover:bg-accent'
                    }`}
                  >
                    {a === 'confirm' ? <Check size={12} /> : a === 'reject' ? <X size={12} /> : a === 'rename' ? <Edit2 size={12} /> : <Link2 size={12} />}
                    {ACTION_LABEL[a]}
                  </button>
                ))}
                {busy === item.id && <Loader2 size={13} className="animate-spin text-muted-foreground" />}
              </div>
            )}
          </div>
        );
      })}
      {!shown.length && pending.length === 0 && !showDone && (
        <div className="p-6 text-center text-xs text-muted-foreground">Nothing left to check.</div>
      )}
    </div>
  );
}

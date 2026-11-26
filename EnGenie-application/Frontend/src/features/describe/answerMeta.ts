import type { DescribeAgentResult } from '../../services/pidDescribeService';
import type { ChatEntry } from './types';

/** How the backend read the message (agents/describe/services/turn_analysis.py). */
export const MODE_LABELS: Record<string, string> = {
  question: 'Answer',
  build: 'Build',
  update: 'Update',
  mixed: 'Build + Answer',
};

/** The parts of an assistant chat entry that come from input analysis and the
 *  grounded answer: the mode badge, and the cited tags as clickable chips that
 *  focus the node on the canvas. */
export function answerMeta(res: DescribeAgentResult): Pick<ChatEntry, 'mode' | 'results' | 'sources'> {
  const citations = Array.isArray(res.citations) ? res.citations.filter(t => typeof t === 'string' && t) : [];
  return {
    mode: res.mode || undefined,
    results: citations.length
      ? citations.map(tag => ({ tag, title: tag, detail: '' }))
      : undefined,
    sources: Array.isArray(res.sources) && res.sources.length ? res.sources : undefined,
  };
}

/** The digitiser's review queue (Backend domain/solution/services/digitise_review.py). */

export type ReviewKind = 'tag' | 'link' | 'missing';
export type ReviewStatus = 'pending' | 'confirmed' | 'rejected' | 'corrected';
export type ReviewAction = 'confirm' | 'reject' | 'rename' | 'add_link' | 'remove_link';

export interface ReviewItem {
  id: string;
  kind: ReviewKind;
  code: string;
  tags: string[];
  link?: [string, string, string] | null;
  reason: string;
  confidence: number;
  status: ReviewStatus;
  decision?: { action: ReviewAction; correction?: Record<string, string>; result?: string } | null;
}

export interface ReviewQueue {
  pid?: string;
  items: ReviewItem[];
  counts: Partial<Record<ReviewStatus, number>>;
}

function headers(): Record<string, string> {
  const token = localStorage.getItem('auth_token');
  return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

export async function getReviewQueue(sessionId: string): Promise<ReviewQueue> {
  const resp = await fetch(`/api/pid/review?session_id=${encodeURIComponent(sessionId)}`, {
    headers: headers(),
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`Review queue: server returned ${resp.status}`);
  return resp.json();
}

export async function resolveReviewItem(
  sessionId: string,
  itemId: string,
  action: ReviewAction,
  correction?: Record<string, string>
): Promise<{ id: string; status: ReviewStatus; counts?: ReviewQueue['counts']; pid_graph?: any; error?: string }> {
  const resp = await fetch('/api/pid/review/resolve', {
    method: 'POST',
    headers: headers(),
    credentials: 'include',
    body: JSON.stringify({ session_id: sessionId, item_id: itemId, action, correction }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.error || body.detail || `Server returned ${resp.status}`);
  return body;
}

/** The actions that make sense for an item: a tag can be renamed, a link removed,
 *  a probable miss answered by adding the missing link. */
export function actionsFor(item: Pick<ReviewItem, 'kind'>): ReviewAction[] {
  if (item.kind === 'tag') return ['confirm', 'rename', 'reject'];
  if (item.kind === 'link') return ['confirm', 'reject'];
  return ['add_link', 'confirm'];
}

export interface DescribeAgentOp {
  tool?: string;
  result?: string;
  [k: string]: unknown;
}

export interface DescribeAgentResult {
  status: string;
  agent?: string | null;
  reply?: string | null;
  title?: string | null;
  solution_design?: unknown;
  ops?: DescribeAgentOp[];
  pid_graph?: any;
  pending_delete?: { tags?: string[]; resolved?: string; [k: string]: unknown };
  error?: string;
  /** build | update | question | mixed | chat: how the message was read */
  mode?: string | null;
  analysis?: { mode?: string; steps?: { kind: string; message: string }[]; standalone?: string; method?: string } | null;
  /** tags the answer cites, all checked to exist on the drawing */
  citations?: string[];
  /** knowledge cards the answer was retrieved from */
  sources?: string[];
}

export interface DescribeSession {
  id: string;
  projectId?: string;
  title: string;
  created_at: string;
  messages_count?: number;
}

export interface DescribeMessageRow {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  reasoning?: string;
  ops?: DescribeAgentOp[];
  pendingDelete?: any;
  timestamp: string;
  agent?: string;
  mode?: string;
  citations?: string[];
  sources?: string[];
}

function getAuthHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extraHeaders,
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function describeAgentTurn(
  sessionId: string,
  message: string,
  history: Array<{ role: string; content: string }> = [],
  attachments?: Array<{ name: string; kind: string; base64?: string; mimeType?: string }>
): Promise<DescribeAgentResult> {
  const resp = await fetch('/api/pid/describe', {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      session_id: sessionId,
      message,
      history,
      attachments,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || err.detail || `Server returned ${resp.status}`);
  }

  return await resp.json();
}

export async function describeAgentResolve(
  sessionId: string,
  confirmed: boolean
): Promise<DescribeAgentResult> {
  const resp = await fetch('/api/pid/describe/resolve', {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      session_id: sessionId,
      confirmed,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || err.detail || `Server returned ${resp.status}`);
  }

  return await resp.json();
}

// ── Local Session Storage Management ─────────────────────────────────────────

const SESSIONS_KEY = (pid: string) => `engenie_describe_sessions_${pid || 'default'}`;
const MESSAGES_KEY = (sid: string) => `engenie_describe_messages_${sid}`;

export async function listDescribeSessions(projectId: string): Promise<DescribeSession[]> {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY(projectId));
    if (raw) return JSON.parse(raw);
  } catch {}
  return [];
}

export async function createDescribeSession(projectId: string, title = 'New Design Thread'): Promise<{ id: string }> {
  const id = `session_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
  const sessions = await listDescribeSessions(projectId);
  const newSession: DescribeSession = {
    id,
    projectId,
    title,
    created_at: new Date().toISOString(),
    messages_count: 0,
  };
  sessions.unshift(newSession);
  localStorage.setItem(SESSIONS_KEY(projectId), JSON.stringify(sessions));
  return { id };
}

export async function duplicateDescribeSession(
  projectId: string,
  sourceSessionId: string,
  newTitle?: string
): Promise<{ id: string; title: string }> {
  const sessions = await listDescribeSessions(projectId);
  const sourceSession = sessions.find(s => s.id === sourceSessionId);
  const title = newTitle || (sourceSession ? `${sourceSession.title} (Fork)` : 'Branched Thread');
  const id = `session_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
  const newSession: DescribeSession = {
    id,
    projectId,
    title,
    created_at: new Date().toISOString(),
    messages_count: sourceSession?.messages_count || 0,
  };
  sessions.unshift(newSession);
  localStorage.setItem(SESSIONS_KEY(projectId), JSON.stringify(sessions));

  // Clone messages
  const sourceMessages = await getDescribeMessages(sourceSessionId);
  if (sourceMessages && sourceMessages.length > 0) {
    const clonedMessages = sourceMessages.map(m => ({
      ...m,
      id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      timestamp: new Date().toISOString(),
    }));
    await saveDescribeMessages(id, clonedMessages);
  }

  return { id, title };
}


export async function renameDescribeSession(projectId: string, sessionId: string, title: string): Promise<void> {
  const sessions = await listDescribeSessions(projectId);
  const found = sessions.find(s => s.id === sessionId);
  if (found) {
    found.title = title;
    localStorage.setItem(SESSIONS_KEY(projectId), JSON.stringify(sessions));
  }
}

export async function deleteDescribeSession(projectId: string, sessionId: string): Promise<void> {
  let sessions = await listDescribeSessions(projectId);
  sessions = sessions.filter(s => s.id !== sessionId);
  localStorage.setItem(SESSIONS_KEY(projectId), JSON.stringify(sessions));
  localStorage.removeItem(MESSAGES_KEY(sessionId));
}

export async function getDescribeMessages(sessionId: string): Promise<DescribeMessageRow[]> {
  try {
    const raw = localStorage.getItem(MESSAGES_KEY(sessionId));
    if (raw) return JSON.parse(raw);
  } catch {}
  return [];
}

export async function saveDescribeMessages(sessionId: string, messages: DescribeMessageRow[]): Promise<void> {
  localStorage.setItem(MESSAGES_KEY(sessionId), JSON.stringify(messages));
}

// ── P&ID Solution & Accessory Integration ────────────────────────────────────

export interface IdentifiedAccessory {
  id?: string;
  name?: string;
  productName?: string;
  category?: string;
  instrument_tag?: string;
  parent_tag?: string;
  description?: string;
  specifications?: Record<string, any>;
  mandatory?: boolean;
}

export interface PIDSolutionEnrichmentResult {
  success: boolean;
  session_id: string;
  instruments: any[];
  accessories: IdentifiedAccessory[];
  summary?: string;
  nodes_updated?: number;
  pid_graph?: any;
  error?: string;
}

export async function identifyPIDAccessories(
  sessionId: string,
  tags?: string[]
): Promise<PIDSolutionEnrichmentResult> {
  const resp = await fetch('/api/pid/identify-accessories', {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      session_id: sessionId,
      tags,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || err.detail || `Server returned ${resp.status}`);
  }

  return await resp.json();
}

export async function getPIDAccessories(sessionId: string): Promise<IdentifiedAccessory[]> {
  try {
    const token = localStorage.getItem('auth_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const resp = await fetch(`/api/pid/accessories?session_id=${encodeURIComponent(sessionId)}`, {
      headers,
      credentials: 'include',
    });
    if (!resp.ok) return [];
    const data = await resp.json().catch(() => ({}));
    return data.accessories || [];
  } catch {
    return [];
  }
}

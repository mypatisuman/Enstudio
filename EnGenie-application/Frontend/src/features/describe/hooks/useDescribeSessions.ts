import { useState, useCallback, useEffect, useMemo } from 'react';
import type { ChatEntry, DescribeSession } from '../types';
import * as describeService from '../../../services/pidDescribeService';

function rowToEntry(row: describeService.DescribeMessageRow): ChatEntry {
  let pendingDeletes: string[] | undefined;
  if (row.pendingDelete) {
    if (Array.isArray(row.pendingDelete)) {
      pendingDeletes = row.pendingDelete;
    } else if (typeof row.pendingDelete === 'string') {
      try {
        const parsed = JSON.parse(row.pendingDelete);
        pendingDeletes = Array.isArray(parsed) ? parsed : [row.pendingDelete];
      } catch {
        pendingDeletes = [row.pendingDelete];
      }
    }
  }

  return {
    id: row.id,
    role: row.role === 'user' ? 'user' : 'assistant',
    display: row.content,
    reasoning: row.reasoning,
    ops: row.ops,
    pendingDeletes,
    timestamp: row.timestamp,
    answerMarkdown: true,
    agent: row.agent,
    mode: row.mode,
    results: row.citations?.length ? row.citations.map(tag => ({ tag, title: tag, detail: '' })) : undefined,
    sources: row.sources,
  };
}

function entryToRow(entry: ChatEntry): describeService.DescribeMessageRow {
  return {
    id: entry.id || `msg_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
    role: entry.role,
    content: entry.display,
    reasoning: entry.reasoning,
    ops: entry.ops,
    pendingDelete: entry.pendingDeletes,
    timestamp: entry.timestamp || new Date().toISOString(),
    agent: entry.agent,
    mode: entry.mode,
    citations: entry.results?.map(r => r.tag),
    sources: entry.sources,
  };
}

const PINNED_STORAGE_KEY = 'engenie_pinned_describe_sessions';
const PROJECTS_STORAGE_KEY = 'engenie_describe_session_projects';
const ARCHIVED_STORAGE_KEY = 'engenie_describe_archived_sessions';

export function useDescribeSessions(projectId: string = 'default') {
  const [sessions, setSessions] = useState<DescribeSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatEntry[]>([]);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [sessionToDelete, setSessionToDelete] = useState<DescribeSession | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [thinkMode, setThinkMode] = useState(true);

  // Load pinned IDs from localStorage
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => {
    try {
      const stored = localStorage.getItem(PINNED_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  // Load session projects mapping from localStorage
  const [sessionProjects, setSessionProjects] = useState<Record<string, string>>(() => {
    try {
      const stored = localStorage.getItem(PROJECTS_STORAGE_KEY);
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  });

  // Load archived IDs from localStorage
  const [archivedIds, setArchivedIds] = useState<string[]>(() => {
    try {
      const stored = localStorage.getItem(ARCHIVED_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  const togglePinSession = useCallback((sessionId: string) => {
    setPinnedIds(prev => {
      const next = prev.includes(sessionId) ? prev.filter(id => id !== sessionId) : [...prev, sessionId];
      try {
        localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(next));
      } catch (err) {
        console.error('Failed to save pinned sessions:', err);
      }
      return next;
    });
  }, []);

  const toggleArchiveSession = useCallback((sessionId: string) => {
    setArchivedIds(prev => {
      const next = prev.includes(sessionId) ? prev.filter(id => id !== sessionId) : [...prev, sessionId];
      try {
        localStorage.setItem(ARCHIVED_STORAGE_KEY, JSON.stringify(next));
      } catch (err) {
        console.error('Failed to save archived sessions:', err);
      }
      return next;
    });
  }, []);

  const assignProject = useCallback((sessionId: string, projectName: string) => {
    setSessionProjects(prev => {
      const next = { ...prev, [sessionId]: projectName };
      try {
        localStorage.setItem(PROJECTS_STORAGE_KEY, JSON.stringify(next));
      } catch (err) {
        console.error('Failed to save session projects:', err);
      }
      return next;
    });
  }, []);

  const loadSessions = useCallback(async (pid: string = projectId) => {
    const list = await describeService.listDescribeSessions(pid).catch(() => []);
    setSessions(list);
    return list;
  }, [projectId]);

  const loadSession = useCallback(async (sessionId: string) => {
    const rows = await describeService.getDescribeMessages(sessionId).catch(() => []);
    setChat(rows.map(rowToEntry));
    setActiveSessionId(sessionId);
  }, []);

  const startNewChat = useCallback(async () => {
    setChat([]);
    const r = await describeService.createDescribeSession(projectId).catch(() => null);
    if (r) {
      setActiveSessionId(r.id);
      await loadSessions(projectId);
      return r.id;
    }
    return null;
  }, [projectId, loadSessions]);

  const confirmDeleteSession = useCallback(async (session: DescribeSession) => {
    await describeService.deleteDescribeSession(projectId, session.id).catch(() => {});
    // also remove from pinned if needed
    setPinnedIds(prev => {
      const next = prev.filter(id => id !== session.id);
      localStorage.setItem(PINNED_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
    const list = await loadSessions(projectId);
    if (session.id === activeSessionId) {
      if (list.length > 0) {
        loadSession(list[0].id);
      } else {
        setActiveSessionId(null);
        setChat([]);
      }
    }
    setSessionToDelete(null);
  }, [projectId, activeSessionId, loadSessions, loadSession]);

  const saveSessionTitle = useCallback(async (session: DescribeSession) => {
    setEditingSessionId(null);
    const title = editingTitle.trim();
    if (!title || title === session.title) return;
    await describeService.renameDescribeSession(projectId, session.id, title).catch(() => {});
    loadSessions(projectId);
  }, [projectId, editingTitle, loadSessions]);

  // Persist messages whenever chat updates for the active session
  const persistChat = useCallback(async (sessionId: string, newChat: ChatEntry[]) => {
    const rows = newChat.map(entryToRow);
    await describeService.saveDescribeMessages(sessionId, rows).catch(() => {});
  }, []);

  // Save specific session explicitly
  const saveSession = useCallback(async (session: DescribeSession) => {
    try {
      if (session.id === activeSessionId) {
        const rows = chat.map(entryToRow);
        await describeService.saveDescribeMessages(session.id, rows);
      }
      const list = await describeService.listDescribeSessions(projectId);
      const found = list.find(s => s.id === session.id);
      if (found) {
        (found as any).updated_at = new Date().toISOString();
        localStorage.setItem(`engenie_describe_sessions_${projectId || 'default'}`, JSON.stringify(list));
      }
      await loadSessions(projectId);
      return true;
    } catch (err) {
      console.error('Failed to save session:', err);
      return false;
    }
  }, [activeSessionId, chat, projectId, loadSessions]);

  // Duplicate/fork chat session (Document icon functionality)
  const duplicateSession = useCallback(async (session: DescribeSession) => {
    try {
      if (session.id === activeSessionId && chat.length > 0) {
        const rows = chat.map(entryToRow);
        await describeService.saveDescribeMessages(session.id, rows);
      }
      const result = await describeService.duplicateDescribeSession(projectId, session.id);
      if (result?.id) {
        await loadSessions(projectId);
        await loadSession(result.id);
        return result;
      }
      return null;
    } catch (err) {
      console.error('Failed to duplicate session:', err);
      return null;
    }
  }, [projectId, activeSessionId, chat, loadSessions, loadSession]);

  // Export / Download specific session data (Download icon functionality)
  const downloadSession = useCallback(async (session: DescribeSession) => {
    try {
      let rows: describeService.DescribeMessageRow[] = [];
      if (session.id === activeSessionId && chat.length > 0) {
        rows = chat.map(entryToRow);
      } else {
        rows = await describeService.getDescribeMessages(session.id);
      }

      let graph = null;
      try {
        const stored = localStorage.getItem('active_pid_graph');
        if (stored) graph = JSON.parse(stored);
      } catch {}

      const payload = {
        session: {
          id: session.id,
          title: session.title,
          projectId: session.projectId || projectId,
          project: sessionProjects[session.id] || session.project || 'Default',
          created_at: session.created_at,
          exported_at: new Date().toISOString(),
          message_count: rows.length,
        },
        chat: rows.map(r => ({
          id: r.id,
          role: r.role,
          content: r.content,
          reasoning: r.reasoning,
          timestamp: r.timestamp,
          agent: r.agent,
          citations: r.citations,
        })),
        graph,
      };

      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(payload, null, 2));
      const downloadAnchor = document.createElement('a');
      const safeTitle = (session.title || 'chat_session').replace(/[^a-zA-Z0-9_-]/g, '_');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', `${safeTitle}_session_export.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
      return true;
    } catch (err) {
      console.error('Failed to download session:', err);
      return false;
    }
  }, [activeSessionId, chat, projectId, sessionProjects]);


  // Hydrate sessions with pinned, archived and project status
  const hydratedSessions = useMemo(() => {
    return sessions.map(s => ({
      ...s,
      pinned: pinnedIds.includes(s.id),
      archived: archivedIds.includes(s.id),
      project: sessionProjects[s.id] || undefined,
    }));
  }, [sessions, pinnedIds, archivedIds, sessionProjects]);

  // Filtered sessions based on search
  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return hydratedSessions;
    const q = searchQuery.toLowerCase();
    return hydratedSessions.filter(s => s.title.toLowerCase().includes(q));
  }, [hydratedSessions, searchQuery]);

  // Pinned sessions list (only active, unarchived)
  const pinnedSessions = useMemo(() => {
    return filteredSessions.filter(s => s.pinned && !s.archived);
  }, [filteredSessions]);

  // Archived sessions list
  const archivedSessions = useMemo(() => {
    return filteredSessions.filter(s => s.archived);
  }, [filteredSessions]);

  // Projects list (unique project names)
  const projectList = useMemo(() => {
    const set = new Set<string>();
    Object.values(sessionProjects).forEach(p => {
      if (p.trim()) set.add(p.trim());
    });
    // Default demo projects if none exist
    if (set.size === 0) {
      set.add('Refinery Unit 4');
      set.add('Cryogenic Distillation');
    }
    return Array.from(set);
  }, [sessionProjects]);

  // Chronologically grouped active unpinned sessions (excluding archived)
  const chronologicalGroups = useMemo(() => {
    const unpinned = filteredSessions.filter(s => !s.pinned && !s.archived);
    const now = Date.now();
    const oneDay = 24 * 60 * 60 * 1000;

    const today: DescribeSession[] = [];
    const yesterday: DescribeSession[] = [];
    const previous7Days: DescribeSession[] = [];
    const older: DescribeSession[] = [];

    unpinned.forEach(s => {
      const time = s.updated_at ? new Date(s.updated_at).getTime() : now;
      const diff = now - time;

      if (diff < oneDay) {
        today.push(s);
      } else if (diff < 2 * oneDay) {
        yesterday.push(s);
      } else if (diff < 7 * oneDay) {
        previous7Days.push(s);
      } else {
        older.push(s);
      }
    });

    return {
      today,
      yesterday,
      previous7Days,
      older,
    };
  }, [filteredSessions]);

  // Initial load
  useEffect(() => {
    setChat([]);
    setActiveSessionId(null);
    setSessions([]);
    loadSessions(projectId).then(list => {
      if (list.length > 0) {
        loadSession(list[0].id);
      } else {
        startNewChat();
      }
    });
  }, [projectId, loadSessions, loadSession, startNewChat]);

  return {
    sessions: hydratedSessions,
    pinnedSessions,
    archivedSessions,
    chronologicalGroups,
    projectList,
    activeSessionId,
    setActiveSessionId,
    chat,
    setChat,
    sessionMenuOpen,
    setSessionMenuOpen,
    sessionToDelete,
    setSessionToDelete,
    editingSessionId,
    setEditingSessionId,
    editingTitle,
    setEditingTitle,
    searchQuery,
    setSearchQuery,
    thinkMode,
    setThinkMode,
    togglePinSession,
    toggleArchiveSession,
    assignProject,
    loadSessions,
    loadSession,
    startNewChat,
    confirmDeleteSession,
    saveSessionTitle,
    persistChat,
    saveSession,
    duplicateSession,
    downloadSession,
  };
};

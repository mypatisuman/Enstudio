import { useState, useRef, type KeyboardEvent } from 'react';
import { Bot, Sparkles, X, ChevronRight, RefreshCw } from 'lucide-react';
import { useDescribeSessions } from '../hooks/useDescribeSessions';
import { useAutoScroll } from '../hooks/useAutoScroll';
import { SessionToolbar } from './SessionToolbar';
import { MessageList } from './MessageList';
import { MessageComposer } from './MessageComposer';
import { SessionDeleteModal } from './SessionDeleteModal';
import { describeAgentTurn, describeAgentResolve } from '../../../services/pidDescribeService';
import { requestCanvasFocus } from '../../canvas/focusBus';
import { emitGraphChanged } from '../../canvas/graphEvents';
import type { ChatEntry, PendingAttachment } from '../types';
import { answerMeta } from '../answerMeta';

interface DescribePanelProps {
  projectId?: string;
  onClose?: () => void;
  className?: string;
}

export function DescribePanel({
  projectId = 'default',
  onClose,
  className = '',
}: DescribePanelProps) {
  const {
    sessions,
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
    loadSessions,
    loadSession,
    startNewChat,
    confirmDeleteSession,
    saveSessionTitle,
    persistChat,
  } = useDescribeSessions(projectId);

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useAutoScroll(bottomRef, chat, loading);

  const handleSend = async (overrideText?: string) => {
    const textToSend = (overrideText ?? input).trim();
    if ((!textToSend && attachments.length === 0) || loading) return;

    setInput('');
    const currentAttachments = [...attachments];
    setAttachments([]);

    let sid = activeSessionId;
    if (!sid) {
      await startNewChat();
      sid = activeSessionId || `session_${Date.now()}`;
    }

    const userEntry: ChatEntry = {
      role: 'user',
      display: textToSend,
      attachments: currentAttachments.map(a => ({ name: a.name, kind: a.kind })),
      timestamp: new Date().toISOString(),
    };

    const updatedChatWithUser = [...chat, userEntry];
    setChat(updatedChatWithUser);
    setLoading(true);

    try {
      // Build history for backend multi-agent turn
      const history = chat.map(c => ({
        role: c.role,
        content: c.display,
      }));

      const res = await describeAgentTurn(
        sid,
        textToSend,
        history,
        currentAttachments.map(a => ({
          name: a.name,
          kind: a.kind,
          base64: a.base64,
          mimeType: a.kind === 'pdf' ? 'application/pdf' : 'image/png',
        }))
      );

      // Parse operations or changes
      let nodesAdded = 0;
      let edgesAdded = 0;
      let nodesUpdated = 0;

      if (res.ops && Array.isArray(res.ops)) {
        res.ops.forEach((op: any) => {
          const tool = op.tool || '';
          if (tool.includes('add_node') || tool.includes('create_equipment')) nodesAdded++;
          else if (tool.includes('add_edge') || tool.includes('connect')) edgesAdded++;
          else if (tool.includes('update') || tool.includes('modify')) nodesUpdated++;
        });
      }

      const pendingDeletes =
        res.status === 'pending_delete' && res.pending_delete?.tags
          ? res.pending_delete.tags
          : undefined;

      const replyText =
        res.reply ||
        (pendingDeletes?.length
          ? `Please confirm deletion of ${pendingDeletes.join(', ')}.`
          : 'Agent finished execution with no text response.');

      const assistantEntry: ChatEntry = {
        role: 'assistant',
        display: replyText,
        agent: res.agent || undefined,
        reasoning: typeof res.solution_design === 'string' ? res.solution_design : undefined,
        nodesAdded: nodesAdded || undefined,
        edgesAdded: edgesAdded || undefined,
        nodesUpdated: nodesUpdated || undefined,
        pendingDeletes,
        ops: res.ops,
        solution_design: res.solution_design,
        timestamp: new Date().toISOString(),
        answerMarkdown: true,
        ...answerMeta(res),
      };

      const finalChat = [...updatedChatWithUser, assistantEntry];
      setChat(finalChat);
      await persistChat(sid, finalChat);

      if (res.pid_graph && Array.isArray(res.pid_graph.nodes) && res.pid_graph.nodes.length > 0) {
        try {
          localStorage.setItem('active_pid_graph', JSON.stringify(res.pid_graph));
          sessionStorage.setItem('active_pid_graph', JSON.stringify(res.pid_graph));
        } catch (e) {
          console.warn('Failed to persist active_pid_graph in DescribePanel:', e);
        }
        emitGraphChanged(projectId);
      } else if (nodesAdded > 0 || edgesAdded > 0 || nodesUpdated > 0) {
        emitGraphChanged(projectId);
      }

      // Rename session if title generated
      if (res.title?.trim()) {
        await saveSessionTitle({ id: sid, title: res.title.trim() });
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      const errorEntry: ChatEntry = {
        role: 'assistant',
        display: `**Agent Error:** ${errMsg}`,
        isError: true,
        timestamp: new Date().toISOString(),
      };
      const finalChat = [...updatedChatWithUser, errorEntry];
      setChat(finalChat);
      await persistChat(sid, finalChat);
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleConfirmDeletes = async (entryIndex: number, tags: string[]) => {
    if (!activeSessionId) return;
    try {
      await describeAgentResolve(activeSessionId, true);
      emitGraphChanged(projectId);

      const updated = chat.map((entry, idx) =>
        idx === entryIndex
          ? {
              ...entry,
              deleteResolution: 'confirmed' as const,
              nodesDeleted: tags.length,
            }
          : entry
      );
      setChat(updated);
      await persistChat(activeSessionId, updated);
    } catch (e: unknown) {
      console.error('Failed to resolve delete:', e);
    }
  };

  const handleCancelDeletes = async (entryIndex: number) => {
    if (!activeSessionId) return;
    try {
      await describeAgentResolve(activeSessionId, false);

      const updated = chat.map((entry, idx) =>
        idx === entryIndex
          ? {
              ...entry,
              deleteResolution: 'cancelled' as const,
            }
          : entry
      );
      setChat(updated);
      await persistChat(activeSessionId, updated);
    } catch (e: unknown) {
      console.error('Failed to cancel delete:', e);
    }
  };

  const handleBuildCanvas = (overrideText?: string) => {
    const hasImage = attachments.some(a => a.kind === 'image' || a.kind === 'pdf');
    if (hasImage) {
      const prompt = overrideText || (input.trim()
        ? `${input.trim()} — Extract and build complete P&ID canvas from this uploaded diagram`
        : 'Extract and build complete P&ID canvas from this uploaded diagram');
      handleSend(prompt);
    } else {
      handleSend(overrideText || 'Build Solution on Canvas');
    }
  };

  const hasImageAttached = attachments.some(a => a.kind === 'image' || a.kind === 'pdf');
  const canBuildSolution = chat.some(
    c =>
      c.role === 'assistant' &&
      (c.display?.toLowerCase()?.includes('build solution on canvas') ||
        c.display?.toLowerCase()?.includes('build now') ||
        !!c.solution_design)
  );

  return (
    <div
      className={`flex flex-col h-full bg-card border-l border-border relative z-20 shadow-2xl overflow-hidden ${className}`}
    >
      {/* Top Header */}
      <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-border bg-card/80 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
            <Sparkles size={14} />
          </div>
          <div>
            <h3 className="font-semibold text-xs text-foreground tracking-tight flex items-center gap-1.5">
              Describe Copilot
              <span className="px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 font-mono text-[9px]">
                8 Agents
              </span>
            </h3>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
              title="Close panel"
            >
              <X size={15} />
            </button>
          )}
        </div>
      </div>

      {/* Session Toolbar */}
      <SessionToolbar
        sessions={sessions}
        activeSessionId={activeSessionId}
        sessionMenuOpen={sessionMenuOpen}
        setSessionMenuOpen={setSessionMenuOpen}
        editingSessionId={editingSessionId}
        setEditingSessionId={setEditingSessionId}
        editingTitle={editingTitle}
        setEditingTitle={setEditingTitle}
        onSelectSession={loadSession}
        onSaveTitle={saveSessionTitle}
        onRequestDelete={setSessionToDelete}
        onNewChat={startNewChat}
      />

      {/* Message List */}
      <MessageList
        chat={chat}
        loading={loading}
        bottomRef={bottomRef}
        onCancelDeletes={handleCancelDeletes}
        onConfirmDeletes={handleConfirmDeletes}
        onFocusTag={requestCanvasFocus}
        onSendPreset={preset => handleSend(preset)}
        onBuildCanvas={() => handleBuildCanvas('Build Solution on Canvas')}
      />

      {/* Message Composer */}
      <MessageComposer
        input={input}
        setInput={setInput}
        onKeyDown={handleKeyDown}
        onSend={() => handleSend()}
        onBuildCanvas={() => handleBuildCanvas()}
        hasImageAttached={hasImageAttached}
        canBuildSolution={canBuildSolution}
        loading={loading}
        textareaRef={textareaRef}
        attachments={attachments}
        setAttachments={setAttachments}
      />

      {/* Session Delete Modal */}
      {sessionToDelete && (
        <SessionDeleteModal
          session={sessionToDelete}
          onConfirm={() => confirmDeleteSession(sessionToDelete)}
          onClose={() => setSessionToDelete(null)}
        />
      )}
    </div>
  );
}

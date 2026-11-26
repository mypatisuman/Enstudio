import { ChevronDown, Plus, Pencil, Trash2, MessageSquare, Check, X } from 'lucide-react';
import type { DescribeSession } from '../types';

interface SessionToolbarProps {
  sessions: DescribeSession[];
  activeSessionId: string | null;
  sessionMenuOpen: boolean;
  setSessionMenuOpen: (v: boolean | ((o: boolean) => boolean)) => void;
  editingSessionId: string | null;
  setEditingSessionId: (id: string | null) => void;
  editingTitle: string;
  setEditingTitle: (t: string) => void;
  onSelectSession: (id: string) => void;
  onSaveTitle: (session: DescribeSession) => void;
  onRequestDelete: (session: DescribeSession) => void;
  onNewChat: () => void;
}

export function SessionToolbar({
  sessions,
  activeSessionId,
  sessionMenuOpen,
  setSessionMenuOpen,
  editingSessionId,
  setEditingSessionId,
  editingTitle,
  setEditingTitle,
  onSelectSession,
  onSaveTitle,
  onRequestDelete,
  onNewChat,
}: SessionToolbarProps) {
  const activeSession = sessions.find(s => s.id === activeSessionId);

  return (
    <div className="flex-shrink-0 flex items-center justify-between gap-2 px-3 py-2 border-b border-border bg-card/60 backdrop-blur-sm">
      <div className="relative flex-1 min-w-0">
        <button
          type="button"
          onClick={() => setSessionMenuOpen(o => !o)}
          className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg border border-border bg-background hover:bg-accent/10 transition-colors text-xs font-medium text-foreground truncate shadow-sm"
        >
          <div className="flex items-center gap-2 truncate">
            <MessageSquare size={13} className="text-primary flex-shrink-0" />
            <span className="truncate">
              {activeSession ? activeSession.title : 'New Design Session'}
            </span>
          </div>
          <ChevronDown size={13} className="flex-shrink-0 text-muted-foreground transition-transform" />
        </button>

        {sessionMenuOpen && (
          <>
            <div
              className="fixed inset-0 z-40"
              onClick={() => setSessionMenuOpen(false)}
            />
            <div className="absolute top-full left-0 right-0 mt-1.5 bg-popover border border-border rounded-xl shadow-2xl z-50 max-h-64 overflow-y-auto p-1 text-xs">
              <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                Saved Sessions ({sessions.length})
              </div>
              {sessions.length === 0 ? (
                <div className="px-3 py-4 text-center text-muted-foreground text-xs">
                  No sessions yet.
                </div>
              ) : (
                sessions.map(s => (
                  <div
                    key={s.id}
                    onClick={() => {
                      if (editingSessionId !== s.id) {
                        onSelectSession(s.id);
                        setSessionMenuOpen(false);
                      }
                    }}
                    className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-colors ${
                      s.id === activeSessionId
                        ? 'bg-primary/10 text-primary font-medium'
                        : 'hover:bg-accent text-foreground'
                    }`}
                  >
                    {editingSessionId === s.id ? (
                      <div className="flex items-center gap-1.5 flex-1 min-w-0" onClick={e => e.stopPropagation()}>
                        <input
                          autoFocus
                          value={editingTitle}
                          onChange={e => setEditingTitle(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              onSaveTitle(s);
                            }
                            if (e.key === 'Escape') {
                              e.preventDefault();
                              setEditingSessionId(null);
                            }
                          }}
                          className="flex-1 min-w-0 bg-background border border-primary rounded px-2 py-0.5 text-xs text-foreground outline-none"
                        />
                        <button
                          onClick={() => onSaveTitle(s)}
                          className="p-1 hover:bg-primary/20 text-primary rounded"
                          title="Save"
                        >
                          <Check size={12} />
                        </button>
                        <button
                          onClick={() => setEditingSessionId(null)}
                          className="p-1 hover:bg-muted text-muted-foreground rounded"
                          title="Cancel"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ) : (
                      <>
                        <span className="flex-1 truncate">{s.title}</span>
                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            type="button"
                            onClick={e => {
                              e.stopPropagation();
                              setEditingSessionId(s.id);
                              setEditingTitle(s.title);
                            }}
                            title="Rename"
                            className="p-1 hover:bg-background/80 rounded text-muted-foreground hover:text-foreground"
                          >
                            <Pencil size={11} />
                          </button>
                          <button
                            type="button"
                            onClick={e => {
                              e.stopPropagation();
                              onRequestDelete(s);
                              setSessionMenuOpen(false);
                            }}
                            title="Delete"
                            className="p-1 hover:bg-red-500/20 rounded text-muted-foreground hover:text-red-500"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={onNewChat}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border bg-background hover:bg-accent hover:border-primary/50 text-foreground transition-all text-xs font-medium shadow-sm flex-shrink-0"
      >
        <Plus size={13} className="text-primary" />
        <span>New</span>
      </button>
    </div>
  );
}

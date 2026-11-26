import React, { useState, useRef, useEffect, KeyboardEvent } from 'react';
import { PIDStudioLayout } from '../../components/PIDStudio/PIDStudioLayout';
import { DescribeSidebar } from '../../features/describe/components/DescribeSidebar';
import { DescribeLandingState } from '../../features/describe/components/DescribeLandingState';
import { MessageList } from '../../features/describe/components/MessageList';
import { MessageComposer } from '../../features/describe/components/MessageComposer';
import { LibraryModal } from '../../features/describe/components/LibraryModal';
import { SessionDeleteModal } from '../../features/describe/components/SessionDeleteModal';
import { PIDHelpModal } from '../../components/PIDStudio/PIDHelpModal';
import { PIDSettingsModal } from '../../components/PIDStudio/PIDSettingsModal';
import { useDescribeSessions } from '../../features/describe/hooks/useDescribeSessions';
import { useAutoScroll } from '../../features/describe/hooks/useAutoScroll';
import { describeAgentTurn, describeAgentResolve } from '../../services/pidDescribeService';
import { requestCanvasFocus } from '../../features/canvas/focusBus';
import { emitGraphChanged, onGraphChanged } from '../../features/canvas/graphEvents';
import type { ChatEntry, PendingAttachment } from '../../features/describe/types';
import { answerMeta } from '../../features/describe/answerMeta';
import PIDCanvasView from '../../components/PIDStudio/PIDCanvasView';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  PanelLeft,
  LayoutDashboard,
  UploadCloud,
  CheckSquare,
  MessageSquareCode,
  ShieldAlert,
  Download,
  Settings,
  HelpCircle,
  Workflow,
  Sparkles,
  Bot,
  Layers,
  Columns,
  Maximize2,
  Minimize2,
  Network,
  User,
  LogOut,
  Package,
  Database,
  BarChart3,
  Coins,
  Gauge,
} from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import NotificationBell from '@/components/NotificationBell';
import { useAuth } from '@/contexts/AuthContext';
import { ProfileEditDialog } from '@/components/ProfileEditDialog';
import ProjectListDialog from '@/components/ProjectListDialog';
import { useToast } from '@/hooks/use-toast';

export default function PIDDescribePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [helpOpen, setHelpOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const solutionTitle =
    localStorage.getItem('active_solution_title') ||
    sessionStorage.getItem('active_solution_title') ||
    'Engineering Solution P&ID';

  const NAV_TABS = [
    { to: '/pid-studio/dashboard', label: 'Overview', icon: LayoutDashboard },
    { to: '/pid-studio/ingest', label: 'Ingest Scan', icon: UploadCloud },
    { to: '/pid-studio/review', label: 'Review', icon: CheckSquare },
    { to: '/pid-studio/canvas', label: 'CAD Canvas', icon: Network },
    { to: '/pid-studio/describe', label: 'Describe Copilot', icon: MessageSquareCode },
    { to: '/pid-studio/validation', label: 'Validation', icon: ShieldAlert },
    { to: '/pid-studio/export', label: 'Export', icon: Download },
  ];
  const projectId =
    localStorage.getItem('active_pid_session_id') ||
    sessionStorage.getItem('active_pid_session_id') ||
    'default';

  const {
    sessions,
    pinnedSessions,
    archivedSessions,
    chronologicalGroups,
    projectList,
    activeSessionId,
    setActiveSessionId,
    chat,
    setChat,
    sessionToDelete,
    setSessionToDelete,
    loadSessions,
    loadSession,
    startNewChat,
    confirmDeleteSession,
    saveSessionTitle,
    persistChat,
    togglePinSession,
    toggleArchiveSession,
    assignProject,
    saveSession,
    duplicateSession,
    downloadSession,
    thinkMode,
    setThinkMode,
  } = useDescribeSessions(projectId);

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [viewMode, setViewMode] = useState<'chat' | 'work'>('chat');

  // Modals state
  const [libraryModalOpen, setLibraryModalOpen] = useState(false);
  const [isProfileEditOpen, setIsProfileEditOpen] = useState(false);
  const [isProjectListOpen, setIsProjectListOpen] = useState(false);

  const { toast } = useToast();
  const { user, logout } = useAuth();

  const profileFullName = user?.firstName && user?.lastName
    ? `${user.firstName} ${user.lastName}`
    : user?.email || "User";
  const profileButtonLabel = user?.firstName || user?.email || "User";
  const profileInitial = profileButtonLabel.charAt(0).toUpperCase();

  const handleSave = () => {
    try {
      if (activeSessionId) {
        persistChat(activeSessionId, chat);
      }
      localStorage.setItem('active_pid_last_saved', new Date().toISOString());
      toast({
        title: "Workspace Saved",
        description: "Describe conversation and workspace state saved successfully.",
      });
    } catch (err) {
      toast({
        title: "Save Failed",
        description: "Could not save current workspace state.",
        variant: "destructive",
      });
    }
  };

  const handleNew = async () => {
    try {
      setInput('');
      setAttachments([]);
      await startNewChat();
      toast({
        title: "New Session Created",
        description: "Started a fresh Describe workspace session.",
      });
    } catch (err) {
      toast({
        title: "Error",
        description: "Could not start a new session.",
        variant: "destructive",
      });
    }
  };

  const handleProjectSelect = (project: any) => {
    const selectedId = project.id || project.projectId || project._id;
    if (selectedId) {
      localStorage.setItem('active_pid_session_id', selectedId);
      sessionStorage.setItem('active_pid_session_id', selectedId);
      if (project.projectName || project.project_name) {
        localStorage.setItem('active_solution_title', project.projectName || project.project_name);
      }
      loadSessions(selectedId);
      toast({
        title: "Project Opened",
        description: `Loaded project: ${project.projectName || project.project_name || selectedId}`,
      });
    }
    setIsProjectListOpen(false);
  };

  const handleProjectDelete = (projectIdToDelete: string) => {
    // ProjectListDialog handles its own API deletion
  };

  const handleDownloadWorkflow = () => {
    try {
      const payload = {
        sessionId: activeSessionId,
        projectId,
        solutionTitle,
        messagesCount: chat.length,
        chat: chat.map(c => ({
          role: c.role,
          content: c.display,
          attachments: c.attachments,
          timestamp: c.timestamp,
        })),
        graph: graphData,
        exportedAt: new Date().toISOString(),
      };
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(payload, null, 2));
      const downloadAnchor = document.createElement('a');
      const safeTitle = (solutionTitle || 'Describe_Workspace').replace(/[^a-zA-Z0-9_-]/g, '_');
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", `${safeTitle}_workflow_data.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
      toast({
        title: "Download Complete",
        description: "Workflow and session data exported successfully.",
      });
    } catch (err) {
      toast({
        title: "Download Failed",
        description: "Could not export workflow data.",
        variant: "destructive",
      });
    }
  };

  // Active Live Graph Data for "+ Work" split view
  const [graphData, setGraphData] = useState<any>(() => {
    try {
      const stored = localStorage.getItem('active_pid_graph');
      return stored ? JSON.parse(stored) : { nodes: [], edges: [] };
    } catch {
      return { nodes: [], edges: [] };
    }
  });

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useAutoScroll(bottomRef, chat, loading);

  // Synchronize graph updates
  useEffect(() => {
    const unsubscribe = onGraphChanged(() => {
      try {
        const stored = localStorage.getItem('active_pid_graph');
        if (stored) setGraphData(JSON.parse(stored));
      } catch {}
    });
    return unsubscribe;
  }, []);

  const handleSend = async (overrideText?: string, pendingAtts?: PendingAttachment[]) => {
    const textToSend = (overrideText ?? input).trim();
    const currentAttachments = pendingAtts ?? attachments;
    if ((!textToSend && currentAttachments.length === 0) || loading) return;

    setInput('');
    setAttachments([]);

    let sid = activeSessionId;
    if (!sid) {
      const newId = await startNewChat();
      sid = newId || `session_${Date.now()}`;
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

    // Automatic tag focus intent check (from standard-main-S DescribeScreen)
    const tagMatch = textToSend.match(/\b([A-Z]{1,4}-\d{1,4}[A-Z]?)\b/i);
    if (tagMatch) {
      const matchedTag = tagMatch[1].toUpperCase();
      requestCanvasFocus(matchedTag);
      const lower = textToSend.toLowerCase();
      if (lower.includes('focus') || lower.includes('locate') || lower.includes('where is') || lower.includes('find') || lower.includes('show me')) {
        setViewMode('work');
      }
    }

    try {
      const history = chat.map(c => ({
        role: c.role,
        content: c.display,
      }));

      // Augment prompt with think mode instruction if enabled
      const finalPrompt = thinkMode
        ? `[Mode: Deep Engineering Multi-Agent Deliberation]\n${textToSend}`
        : textToSend;

      const res = await describeAgentTurn(
        sid,
        finalPrompt,
        history,
        currentAttachments.map(a => ({
          name: a.name,
          kind: a.kind,
          base64: a.base64,
          mimeType: a.kind === 'pdf' ? 'application/pdf' : 'image/png',
        }))
      );

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
        setGraphData(res.pid_graph);
        try {
          localStorage.setItem('active_pid_graph', JSON.stringify(res.pid_graph));
          sessionStorage.setItem('active_pid_graph', JSON.stringify(res.pid_graph));
        } catch (e) {
          console.warn('Failed to persist active_pid_graph to storage:', e);
        }
        emitGraphChanged(projectId);
      } else if (nodesAdded > 0 || edgesAdded > 0 || nodesUpdated > 0) {
        emitGraphChanged(projectId);
      }

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
      handleSend(prompt, attachments);
    } else {
      handleSend(overrideText || 'Build Solution on Canvas');
    }
    setViewMode('work');
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
    <PIDStudioLayout isFlush noHeader>
      <div className="flex h-full w-full bg-[#0d0d0d] text-zinc-100 overflow-hidden font-sans select-none">
        {/* ChatGPT Left Sidebar */}
        <DescribeSidebar
          sessions={sessions}
          pinnedSessions={pinnedSessions}
          archivedSessions={archivedSessions}
          chronologicalGroups={chronologicalGroups}
          projectList={projectList}
          activeSessionId={activeSessionId}
          onSelectSession={loadSession}
          onNewChat={startNewChat}
          onTogglePin={togglePinSession}
          onToggleArchive={toggleArchiveSession}
          onAssignProject={assignProject}
          onSaveSession={saveSession}
          onDuplicateSession={duplicateSession}
          onDownloadSession={downloadSession}
          onOpenProjectList={() => setIsProjectListOpen(true)}
          onSaveTitle={saveSessionTitle}
          onRequestDelete={setSessionToDelete}
          onOpenLibraryModal={() => setLibraryModalOpen(true)}
          isCollapsed={isSidebarCollapsed}
          onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        />

        {/* Main Central Engineering Workspace */}
        <div className="flex-1 flex flex-col h-full min-w-0 bg-[#0d0d0d] relative overflow-hidden">
          {/* In-Page Dark Header Bar */}
          <header className="h-14 border-b border-white/10 flex items-center justify-between px-3.5 bg-[#0d0d0d] z-20 shrink-0 select-none">
            {/* Left: Sidebar Toggle + Solutions Back Link + Solution Title */}
            <div className="flex items-center gap-2.5 min-w-0">
              {isSidebarCollapsed && (
                <button
                  type="button"
                  onClick={() => setIsSidebarCollapsed(false)}
                  title="Open sidebar"
                  className="p-1.5 rounded-lg bg-[#212121] hover:bg-white/10 text-zinc-400 hover:text-white border border-white/10 transition-colors shadow-xs shrink-0"
                >
                  <PanelLeft size={16} />
                </button>
              )}

              <div className="hidden sm:flex items-center gap-2 min-w-0">
                <div className="w-5 h-5 rounded bg-primary/20 border border-primary/30 flex items-center justify-center text-primary shrink-0">
                  <Workflow size={12} />
                </div>
                <span className="text-xs font-semibold text-zinc-200 truncate max-w-[130px] md:max-w-[180px]">
                  {solutionTitle}
                </span>
              </div>
            </div>

            {/* Center: Workflow Tabs */}
            <nav className="hidden md:flex items-center gap-1 p-1 rounded-xl bg-[#171717] border border-white/10 shadow-xs">
              {NAV_TABS.map(tab => {
                const Icon = tab.icon;
                const isActive =
                  location.pathname === tab.to ||
                  (tab.to === '/pid-studio/describe' && (location.pathname === '/chat' || location.pathname === '/describe')) ||
                  (tab.to === '/pid-studio/canvas' && location.pathname.includes('/solution/pid-viewer')) ||
                  (tab.to === '/pid-studio/dashboard' && location.pathname === '/pid-studio');

                return (
                  <NavLink
                    key={tab.to}
                    to={tab.to}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${
                      isActive
                        ? 'bg-white/15 text-white font-semibold border border-white/10 shadow-xs'
                        : 'text-zinc-400 hover:text-zinc-100 hover:bg-white/5'
                    }`}
                  >
                    <Icon size={13} />
                    <span>{tab.label}</span>
                  </NavLink>
                );
              })}
            </nav>

            {/* Right: Actions & Tools */}
            <div className="flex items-center gap-2 shrink-0">
              {/* Standalone Project List Dialog triggered from sidebar */}
              <ProjectListDialog
                open={isProjectListOpen}
                onOpenChange={setIsProjectListOpen}
                onProjectSelect={handleProjectSelect}
                onProjectDelete={handleProjectDelete}
              />

              {/* Notification Bell */}
              <NotificationBell />

              {/* 6. Profile Dropdown */}
              <DropdownMenu>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        className="header-action-btn w-10 h-10 rounded-lg glass-card flex items-center justify-center cursor-pointer"
                        aria-label="Profile"
                      >
                        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center text-white font-bold text-sm ring-1 ring-white/20 shadow-sm">
                          {profileInitial}
                        </div>
                      </button>
                    </DropdownMenuTrigger>
                  </TooltipTrigger>
                  <TooltipContent><p>Profile</p></TooltipContent>
                </Tooltip>
                <DropdownMenuContent
                  className="w-56 mt-1 rounded-xl bg-[#171717]/95 backdrop-blur-2xl border border-white/10 text-zinc-100 shadow-2xl"
                  align="end"
                >
                  <DropdownMenuLabel className="p-0 font-normal">
                    <button
                      type="button"
                      onClick={() => setIsProfileEditOpen(true)}
                      className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-muted/50 transition-colors text-sm font-semibold rounded-md text-left outline-none cursor-pointer"
                      title="Click to edit profile"
                    >
                      <User className="w-4 h-4" />
                      {profileFullName}
                    </button>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />

                  <DropdownMenuItem
                    className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                    onClick={() => navigate('/catalog')}
                  >
                    <Package className="h-4 w-4" />
                    Catalog
                  </DropdownMenuItem>

                  <DropdownMenuItem
                    className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                    onClick={() => navigate('/assets')}
                  >
                    <Database className="h-4 w-4" />
                    Assets
                  </DropdownMenuItem>

                  <DropdownMenuItem
                    className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                    onClick={() => navigate('/pid-studio')}
                  >
                    <Workflow className="h-4 w-4 text-[#0F6CBD] dark:text-[#5FB3E6]" />
                    P&ID Studio
                  </DropdownMenuItem>

                  <DropdownMenuItem
                    className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                    onClick={() => navigate('/usage')}
                  >
                    <BarChart3 className="h-4 w-4" />
                    Usage
                  </DropdownMenuItem>

                  <DropdownMenuItem
                    className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                    onClick={() => navigate('/credits')}
                  >
                    <Coins className="h-4 w-4" />
                    Credits
                  </DropdownMenuItem>

                  {user?.role?.toLowerCase() === "admin" && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                        onClick={() => navigate('/chat/admin')}
                      >
                        <Bot className="h-4 w-4" />
                        User Admin
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                        onClick={() => navigate('/benchmarks')}
                      >
                        <Gauge className="h-4 w-4" />
                        Benchmarks
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                    </>
                  )}

                  <DropdownMenuItem
                    className="flex gap-2 focus:bg-transparent cursor-pointer focus:text-slate-900 dark:focus:text-slate-100"
                    onClick={logout}
                  >
                    <LogOut className="h-4 w-4" />
                    Logout
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <div className="h-4 w-[1px] bg-white/10 mx-0.5" />

              <button
                type="button"
                onClick={() => setHelpOpen(true)}
                className="p-1.5 rounded-lg border border-white/10 bg-[#171717] hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
                title="Shortcuts & Cheatsheet"
              >
                <HelpCircle size={15} />
              </button>

              <button
                type="button"
                onClick={() => setSettingsOpen(true)}
                className="p-1.5 rounded-lg border border-white/10 bg-[#171717] hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
                title="AI Engine Settings"
              >
                <Settings size={15} />
              </button>
            </div>
          </header>

          {/* Mobile/Tablet Sub-Tab Strip */}
          <div className="md:hidden flex items-center gap-1 px-3 py-1.5 border-b border-white/10 bg-[#141414] overflow-x-auto text-xs shrink-0 custom-scrollbar select-none">
            {NAV_TABS.map(tab => {
              const Icon = tab.icon;
              const isActive =
                location.pathname === tab.to ||
                (tab.to === '/pid-studio/describe' && (location.pathname === '/chat' || location.pathname === '/describe')) ||
                (tab.to === '/pid-studio/canvas' && location.pathname.includes('/solution/pid-viewer')) ||
                (tab.to === '/pid-studio/dashboard' && location.pathname === '/pid-studio');

              return (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap transition-all ${
                    isActive
                      ? 'bg-white/15 text-white font-semibold border border-white/10'
                      : 'text-zinc-400 hover:text-white bg-[#171717]'
                  }`}
                >
                  <Icon size={12} />
                  <span>{tab.label}</span>
                </NavLink>
              );
            })}
          </div>

          {/* Body Content */}
          <div className="flex-1 flex min-h-0 overflow-hidden relative">
            {/* Chat Stream Column */}
            <div
              className={`flex flex-col h-full overflow-hidden transition-all duration-300 ${
                viewMode === 'work'
                  ? 'w-full lg:w-[48%] border-r border-white/10 bg-[#0d0d0d]'
                  : 'w-full bg-[#0d0d0d]'
              }`}
            >
              {chat.length === 0 && !loading ? (
                /* Empty state: ChatGPT landing */
                <DescribeLandingState
                  onSend={(text, atts) => handleSend(text, atts)}
                  onBuildCanvas={(text, atts) => {
                    handleSend(text || 'Build Solution on Canvas', atts);
                    setViewMode('work');
                  }}
                  thinkMode={thinkMode}
                  onToggleThinkMode={() => setThinkMode(!thinkMode)}
                />
              ) : (
                /* Active chat conversation stream */
                <>
                  <MessageList
                    chat={chat}
                    loading={loading}
                    bottomRef={bottomRef}
                    onCancelDeletes={handleCancelDeletes}
                    onConfirmDeletes={handleConfirmDeletes}
                    onFocusTag={requestCanvasFocus}
                    onBuildCanvas={() => handleBuildCanvas('Build Solution on Canvas')}
                  />

                  {/* Fixed bottom floating capsule input */}
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
                    thinkMode={thinkMode}
                    onToggleThinkMode={() => setThinkMode(!thinkMode)}
                  />
                </>
              )}
            </div>

            {/* "+ Work" Live Interactive CAD Canvas Split View */}
            {viewMode === 'work' && (
              <div className="hidden lg:flex flex-1 h-full relative bg-[#121212] overflow-hidden flex-col">
                <div className="px-3 py-1.5 border-b border-white/10 bg-[#171717] flex items-center justify-between text-xs text-zinc-300">
                  <span className="font-semibold flex items-center gap-1.5 text-sky-400 font-mono text-[11px]">
                    <Layers size={13} />
                    Live CAD Canvas Preview
                  </span>
                  <span className="text-[10px] text-zinc-400">
                    Auto-updates with agent actions
                  </span>
                </div>
                <div className="flex-1 relative">
                  <PIDCanvasView
                    graph={graphData}
                    onGraphUpdate={updated => {
                      setGraphData(updated);
                      localStorage.setItem('active_pid_graph', JSON.stringify(updated));
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Global Modals for Help, Settings, and Sidebar Navigation */}
        <PIDHelpModal isOpen={helpOpen} onClose={() => setHelpOpen(false)} />
        <PIDSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
        <LibraryModal
          open={libraryModalOpen}
          onClose={() => setLibraryModalOpen(false)}
          onSelectTemplate={prompt => handleSend(prompt)}
        />
        {sessionToDelete && (
          <SessionDeleteModal
            session={sessionToDelete}
            onConfirm={() => confirmDeleteSession(sessionToDelete)}
            onClose={() => setSessionToDelete(null)}
          />
        )}
        <ProfileEditDialog
          open={isProfileEditOpen}
          onOpenChange={setIsProfileEditOpen}
        />
      </div>
    </PIDStudioLayout>
  );
}

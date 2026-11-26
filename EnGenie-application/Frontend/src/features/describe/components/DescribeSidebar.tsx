import React, { useState, useRef, useEffect } from 'react';
import {
  MessageSquarePlus,
  Search,
  PanelLeftClose,
  PanelLeft,
  Pin,
  PinOff,
  Folder,
  FolderOpen,
  Save,
  FileText,
  Download,
  Clock,
  BookOpen,
  MoreHorizontal,
  Trash2,
  Edit2,
  Check,
  X,
  User,
  Sparkles,
  Bot,
  Layers,
  Lightbulb,
  MessageSquare,
  Settings2,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Package,
  Pencil,
  Upload,
  Archive,
  Plus,
} from 'lucide-react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import type { DescribeSession } from '../types';
import { useAuth } from '../../../contexts/AuthContext';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu';
import { useToast } from '@/hooks/use-toast';

interface AppNavItem {
  path: string;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  color: string;
  badge?: string;
  description: string;
}

const APP_NAV_ITEMS: AppNavItem[] = [
  {
    path: '/solution',
    label: 'Solution Studio',
    icon: Lightbulb,
    color: 'text-amber-400',
    description: 'Engineering solution studio',
  },
  {
    path: '/search',
    label: 'Search & Recommender',
    icon: Search,
    color: 'text-sky-400',
    description: 'AI product finder & specs',
  },
  {
    path: '/legacy-chat',
    label: 'Product Chat',
    icon: MessageSquare,
    color: 'text-emerald-400',
    description: 'Interactive catalog chat',
  },
  {
    path: '/catalog',
    label: 'Product Catalog',
    icon: Package,
    color: 'text-violet-400',
    description: 'Component catalog & vendors',
  },
  {
    path: '/configure',
    label: 'Configure',
    icon: Settings2,
    color: 'text-zinc-400',
    description: 'Asset & technical setup',
  },
];

interface DescribeSidebarProps {
  sessions: DescribeSession[];
  pinnedSessions: DescribeSession[];
  archivedSessions?: DescribeSession[];
  chronologicalGroups: {
    today: DescribeSession[];
    yesterday: DescribeSession[];
    previous7Days: DescribeSession[];
    older: DescribeSession[];
  };
  projectList: string[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onTogglePin: (id: string) => void;
  onToggleArchive?: (id: string) => void;
  onAssignProject?: (id: string, projectName: string) => void;
  onSaveSession?: (session: DescribeSession) => Promise<boolean | void> | void;
  onDuplicateSession?: (session: DescribeSession) => Promise<any> | void;
  onDownloadSession?: (session: DescribeSession) => Promise<boolean | void> | void;
  onOpenProjectList?: () => void;
  onSaveTitle: (session: DescribeSession) => void;
  onRequestDelete: (session: DescribeSession) => void;
  onOpenAgentsModal?: () => void;
  onOpenCodexModal?: () => void;
  onOpenLibraryModal: () => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

export function DescribeSidebar({
  sessions,
  pinnedSessions,
  archivedSessions = [],
  chronologicalGroups,
  projectList,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onTogglePin,
  onToggleArchive,
  onAssignProject,
  onSaveSession,
  onDuplicateSession,
  onDownloadSession,
  onOpenProjectList,
  onSaveTitle,
  onRequestDelete,
  onOpenAgentsModal,
  onOpenCodexModal,
  onOpenLibraryModal,
  isCollapsed,
  onToggleCollapse,
}: DescribeSidebarProps) {
  const { toast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [navSectionOpen, setNavSectionOpen] = useState(true);
  const [archivedSectionOpen, setArchivedSectionOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState('');
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchOpen) {
      searchInputRef.current?.focus();
    } else {
      setSearchQuery('');
    }
  }, [searchOpen]);

  const handleStartRename = (s: DescribeSession) => {
    setEditingId(s.id);
    setEditingText(s.title);
    setMenuOpenId(null);
  };

  const handleCommitRename = (s: DescribeSession) => {
    if (editingText.trim() && editingText.trim() !== s.title) {
      onSaveTitle({ ...s, title: editingText.trim() });
    }
    setEditingId(null);
  };

  const handleCancelRename = () => {
    setEditingId(null);
  };

  if (isCollapsed) {
    return (
      <div className="w-12 h-full bg-[#171717] border-r border-white/5 flex flex-col items-center py-3 gap-2 flex-shrink-0 z-30 select-none">
        <button
          type="button"
          onClick={onToggleCollapse}
          title="Expand sidebar"
          className="p-2 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
        >
          <PanelLeft size={18} />
        </button>
        <button
          type="button"
          onClick={onNewChat}
          title="New chat"
          className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-200 hover:text-white transition-colors"
        >
          <MessageSquarePlus size={18} />
        </button>
        <div className="w-6 h-[1px] bg-white/10 my-1" />

        {/* Quick Nav Icons */}
        {APP_NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isItemActive = location.pathname.startsWith(item.path);
          return (
            <NavLink
              key={item.path}
              to={item.path}
              title={item.label}
              className={({ isActive }) =>
                `p-2 rounded-lg transition-colors flex items-center justify-center ${
                  isActive || isItemActive
                    ? 'bg-white/15 text-white shadow-xs'
                    : 'hover:bg-white/10 text-zinc-400 hover:text-white'
                }`
              }
            >
              <Icon size={16} className={item.color} />
            </NavLink>
          );
        })}

        <div className="w-6 h-[1px] bg-white/10 my-1" />

        <button
          type="button"
          onClick={onOpenLibraryModal}
          title="Library"
          className="p-2 rounded-lg hover:bg-white/10 text-purple-400 hover:text-purple-300 transition-colors"
        >
          <BookOpen size={16} />
        </button>
      </div>
    );
  }

  // Filter sessions if search active
  const filtered = searchQuery.trim()
    ? sessions.filter(s => s.title.toLowerCase().includes(searchQuery.toLowerCase()))
    : null;

  const handleSaveSession = async (session: DescribeSession) => {
    setMenuOpenId(null);
    if (onSaveSession) {
      await onSaveSession(session);
    }
    toast({
      title: "Chat Saved",
      description: `"${session.title}" state has been saved.`,
    });
  };

  const handleDuplicateSession = async (session: DescribeSession) => {
    setMenuOpenId(null);
    if (onDuplicateSession) {
      await onDuplicateSession(session);
      toast({
        title: "Chat Branched",
        description: `Created new fork of "${session.title}".`,
      });
    }
  };

  const handleDownloadSession = async (session: DescribeSession) => {
    setMenuOpenId(null);
    if (onDownloadSession) {
      await onDownloadSession(session);
      toast({
        title: "Chat Downloaded",
        description: `Exported "${session.title}" session data file.`,
      });
    }
  };

  const renderSessionItem = (session: DescribeSession) => {
    const isActive = session.id === activeSessionId;
    const isEditing = session.id === editingId;
    const isMenuOpen = menuOpenId === session.id;

    const effectiveProjectList = projectList.length > 0
      ? projectList
      : ['Plant Area A', 'Refinery Unit 4', 'Default Solution'];

    return (
      <div
        key={session.id}
        className={`group relative flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs cursor-pointer transition-all ${
          isActive
            ? 'bg-[#212121] text-white font-medium shadow-xs'
            : 'text-zinc-300 hover:bg-[#212121]/60 hover:text-white'
        }`}
        onClick={() => {
          if (!isEditing) onSelectSession(session.id);
        }}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1 mr-1">
          {session.pinned ? (
            <Pin size={12} className="text-sky-400 flex-shrink-0" />
          ) : session.archived ? (
            <Archive size={12} className="text-zinc-500 flex-shrink-0" />
          ) : (
            <div className="w-1.5 h-1.5 rounded-full bg-zinc-600 group-hover:bg-zinc-400 flex-shrink-0" />
          )}

          {isEditing ? (
            <input
              type="text"
              value={editingText}
              onChange={e => setEditingText(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') handleCommitRename(session);
                if (e.key === 'Escape') handleCancelRename();
              }}
              autoFocus
              className="w-full bg-[#171717] border border-sky-500 rounded px-1.5 py-0.5 text-xs text-white outline-none"
              onClick={e => e.stopPropagation()}
            />
          ) : (
            <span className="truncate leading-tight text-[12px]">{session.title || 'Untitled Design'}</span>
          )}
        </div>

        {/* Action icons or rename controls */}
        {isEditing ? (
          <div className="flex items-center gap-1 flex-shrink-0" onClick={e => e.stopPropagation()}>
            <button
              type="button"
              onClick={() => handleCommitRename(session)}
              className="p-1 rounded hover:bg-white/10 text-emerald-400"
            >
              <Check size={12} />
            </button>
            <button
              type="button"
              onClick={handleCancelRename}
              className="p-1 rounded hover:bg-white/10 text-zinc-400"
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <div
            className="flex items-center gap-0.5 flex-shrink-0"
            onClick={e => e.stopPropagation()}
          >
            {session.pinned && (
              <span title="Pinned chat" className="text-sky-400 opacity-80 group-hover:opacity-100 p-0.5">
                <Pin size={12} />
              </span>
            )}

            {/* Quick action buttons on hover matching the header icons */}
            <button
              type="button"
              title="Save chat"
              onClick={e => {
                e.stopPropagation();
                handleSaveSession(session);
              }}
              className="p-1 rounded hover:bg-white/10 text-zinc-400 hover:text-sky-400 transition-opacity opacity-0 group-hover:opacity-100"
            >
              <Save size={12} />
            </button>

            <button
              type="button"
              title="Download chat"
              onClick={e => {
                e.stopPropagation();
                handleDownloadSession(session);
              }}
              className="p-1 rounded hover:bg-white/10 text-zinc-400 hover:text-sky-400 transition-opacity opacity-0 group-hover:opacity-100"
            >
              <Download size={12} />
            </button>

            <DropdownMenu
              open={isMenuOpen}
              onOpenChange={open => setMenuOpenId(open ? session.id : null)}
            >
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  title="More actions"
                  className={`p-1 rounded hover:bg-white/10 text-zinc-400 hover:text-white transition-opacity ${
                    isMenuOpen ? 'opacity-100 bg-white/10 text-white' : 'opacity-0 group-hover:opacity-100'
                  }`}
                  onClick={e => e.stopPropagation()}
                >
                  <MoreHorizontal size={13} />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                sideOffset={4}
                className="w-52 rounded-xl bg-[#171717]/95 backdrop-blur-2xl border border-white/10 text-zinc-200 shadow-2xl p-1 z-50 text-xs"
                onClick={e => e.stopPropagation()}
              >
                {/* 1. Save Chat (Floppy Disk) */}
                <DropdownMenuItem
                  className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-zinc-200 hover:text-white cursor-pointer"
                  onClick={() => handleSaveSession(session)}
                >
                  <Save size={14} className="text-sky-400" />
                  <span>Save chat</span>
                </DropdownMenuItem>

                {/* 2. New Branch from Chat (Document FileText) */}
                <DropdownMenuItem
                  className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-zinc-200 hover:text-white cursor-pointer"
                  onClick={() => handleDuplicateSession(session)}
                >
                  <FileText size={14} className="text-sky-400" />
                  <span>New branch from chat</span>
                </DropdownMenuItem>

                {/* 3. Project Folder (FolderOpen) */}
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-zinc-200 hover:text-white cursor-pointer">
                    <FolderOpen size={14} className="text-sky-400" />
                    <span className="flex-1">Project folder</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent className="w-52 rounded-xl bg-[#171717]/95 backdrop-blur-2xl border border-white/10 text-zinc-200 shadow-2xl p-1 z-50 text-xs">
                    {onOpenProjectList && (
                      <>
                        <DropdownMenuItem
                          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-sky-400 hover:text-sky-300 font-medium cursor-pointer"
                          onClick={() => {
                            setMenuOpenId(null);
                            onOpenProjectList();
                          }}
                        >
                          <FolderOpen size={13} className="text-sky-400" />
                          <span>Browse all projects...</span>
                        </DropdownMenuItem>
                        <DropdownMenuSeparator className="bg-white/10 my-1" />
                      </>
                    )}
                    {effectiveProjectList.map(proj => (
                      <DropdownMenuItem
                        key={proj}
                        className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-zinc-200 hover:text-white cursor-pointer"
                        onClick={() => {
                          if (onAssignProject) onAssignProject(session.id, proj);
                          toast({
                            title: "Assigned to Project",
                            description: `"${session.title}" assigned to "${proj}".`,
                          });
                        }}
                      >
                        <Folder size={12} className="text-amber-400" />
                        <span className="truncate">{proj}</span>
                        {session.project === proj && <Check size={12} className="ml-auto text-emerald-400" />}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>

                {/* 4. Download / Export Chat (Download Tray) */}
                <DropdownMenuItem
                  className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-zinc-200 hover:text-white cursor-pointer"
                  onClick={() => handleDownloadSession(session)}
                >
                  <Download size={14} className="text-sky-400" />
                  <span>Download chat</span>
                </DropdownMenuItem>

                <DropdownMenuSeparator className="bg-white/10 my-1" />

                {/* 5. Rename */}
                <DropdownMenuItem
                  className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-zinc-200 hover:text-white cursor-pointer"
                  onClick={() => handleStartRename(session)}
                >
                  <Pencil size={13} className="text-zinc-400" />
                  <span>Rename</span>
                </DropdownMenuItem>

                {/* 6. Pin / Unpin */}
                <DropdownMenuItem
                  className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/10 text-zinc-200 hover:text-white cursor-pointer"
                  onClick={() => onTogglePin(session.id)}
                >
                  <Pin size={13} className="text-zinc-400" />
                  <span>{session.pinned ? 'Unpin' : 'Pin to top'}</span>
                </DropdownMenuItem>

                <DropdownMenuSeparator className="bg-white/10 my-1" />

                {/* 7. Delete (Red) */}
                <DropdownMenuItem
                  className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-rose-500/20 text-rose-400 hover:text-rose-300 cursor-pointer"
                  onClick={() => onRequestDelete(session)}
                >
                  <Trash2 size={13} className="text-rose-400" />
                  <span>Delete</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>
    );
  };

  return (
    <aside className="w-[260px] h-full bg-[#171717] border-r border-white/5 flex flex-col flex-shrink-0 text-zinc-300 select-none z-30 font-sans">
      {/* Top Header */}
      <div className="flex items-center justify-between px-3.5 py-3 border-b border-white/5">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400 font-bold text-xs">
            <Sparkles size={14} />
          </div>
          <span className="text-sm font-semibold text-white tracking-tight">
            Copilot
          </span>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setSearchOpen(!searchOpen)}
            title="Search chats"
            className={`p-1.5 rounded-lg transition-colors ${
              searchOpen ? 'bg-white/10 text-white' : 'hover:bg-white/5 text-zinc-400 hover:text-white'
            }`}
          >
            <Search size={15} />
          </button>
          <button
            type="button"
            onClick={onToggleCollapse}
            title="Close sidebar"
            className="p-1.5 rounded-lg hover:bg-white/5 text-zinc-400 hover:text-white transition-colors"
          >
            <PanelLeftClose size={15} />
          </button>
        </div>
      </div>

      {/* Search Input (conditionally visible) */}
      {searchOpen && (
        <div className="px-3 pt-2.5 pb-1">
          <div className="relative">
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search chats..."
              className="w-full bg-[#212121] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder:text-zinc-500 outline-none focus:border-sky-500/50"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-2 text-zinc-400 hover:text-white"
              >
                <X size={12} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Primary New Chat Button */}
      <div className="p-3">
        <button
          type="button"
          onClick={onNewChat}
          className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white text-xs font-medium transition-all shadow-xs group"
        >
          <div className="flex items-center gap-2">
            <MessageSquarePlus size={14} className="text-sky-400" />
            <span>New chat</span>
          </div>
          <span className="text-[10px] text-zinc-500 font-mono group-hover:text-zinc-400">Ctrl+Shift+O</span>
        </button>
      </div>

      {/* Navigation Links: Workspaces & Apps */}
      <div className="px-2 border-b border-white/5 pb-2.5">
        <button
          type="button"
          onClick={() => setNavSectionOpen(!navSectionOpen)}
          className="w-full px-2 pt-1 pb-1 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider flex items-center justify-between hover:text-zinc-300 transition-colors"
        >
          <span>Workspaces</span>
          {navSectionOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>

        {navSectionOpen && (
          <div className="space-y-0.5 mt-1">
            {APP_NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isItemActive = location.pathname.startsWith(item.path);
              return (
                <div
                  key={item.path}
                  className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-all group ${
                    isItemActive
                      ? 'bg-[#212121] text-white font-medium'
                      : 'text-zinc-300 hover:bg-[#212121]/60 hover:text-white'
                  }`}
                >
                  <NavLink
                    to={item.path}
                    className="flex items-center gap-2.5 min-w-0 flex-1 outline-none text-left"
                  >
                    <Icon size={14} className={`${item.color} flex-shrink-0`} />
                    <span className="truncate">{item.label}</span>
                  </NavLink>
                  <a
                    href={item.path}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    title={`Open ${item.label} in new tab`}
                    className="p-1 rounded hover:bg-white/10 text-zinc-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity ml-1 flex-shrink-0"
                  >
                    <ExternalLink size={11} />
                  </a>
                </div>
              );
            })}

            {/* Library */}
            <button
              type="button"
              onClick={onOpenLibraryModal}
              className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-[#212121]/60 text-zinc-300 hover:text-white transition-colors text-left"
            >
              <BookOpen size={14} className="text-purple-400 flex-shrink-0" />
              <span>Library</span>
            </button>
          </div>
        )}
      </div>

      {/* Chat Lists Area (Scrollable) */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-4 text-xs scrollbar-thin scrollbar-thumb-zinc-700">
        {filtered ? (
          <div className="space-y-1">
            <div className="px-2.5 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider">
              Search Results ({filtered.length})
            </div>
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-center text-zinc-500 text-xs">No matching chats</div>
            ) : (
              filtered.map(renderSessionItem)
            )}
          </div>
        ) : (
          <>
            {/* Pinned Section */}
            {pinnedSessions.length > 0 && (
              <div className="space-y-1">
                <div className="px-2.5 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider flex items-center justify-between">
                  <span>Pinned</span>
                  <Pin size={11} className="text-sky-400" />
                </div>
                {pinnedSessions.map(renderSessionItem)}
              </div>
            )}

            {/* Projects Section */}
            {projectList.length > 0 && (
              <div className="space-y-1">
                <div className="px-2.5 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider flex items-center justify-between">
                  <span>Projects</span>
                  <Folder size={11} className="text-amber-400" />
                </div>
                {projectList.map(proj => (
                  <div
                    key={proj}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs text-zinc-400 hover:text-white hover:bg-white/5 cursor-pointer transition-colors"
                  >
                    <Folder size={12} className="text-amber-400 flex-shrink-0" />
                    <span className="truncate">{proj}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Recent History Sections */}
            {chronologicalGroups.today.length > 0 && (
              <div className="space-y-1">
                <div className="px-2.5 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider">
                  Today
                </div>
                {chronologicalGroups.today.map(renderSessionItem)}
              </div>
            )}

            {chronologicalGroups.yesterday.length > 0 && (
              <div className="space-y-1">
                <div className="px-2.5 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider">
                  Yesterday
                </div>
                {chronologicalGroups.yesterday.map(renderSessionItem)}
              </div>
            )}

            {chronologicalGroups.previous7Days.length > 0 && (
              <div className="space-y-1">
                <div className="px-2.5 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider">
                  Previous 7 Days
                </div>
                {chronologicalGroups.previous7Days.map(renderSessionItem)}
              </div>
            )}

            {chronologicalGroups.older.length > 0 && (
              <div className="space-y-1">
                <div className="px-2.5 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider">
                  Older
                </div>
                {chronologicalGroups.older.map(renderSessionItem)}
              </div>
            )}

            {/* Archived Section */}
            {archivedSessions && archivedSessions.length > 0 && (
              <div className="space-y-1 pt-2 border-t border-white/5">
                <button
                  type="button"
                  onClick={() => setArchivedSectionOpen(!archivedSectionOpen)}
                  className="w-full px-2.5 py-1 text-[10px] uppercase font-semibold text-zinc-500 tracking-wider flex items-center justify-between hover:text-zinc-300 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <Archive size={11} className="text-zinc-400" />
                    <span>Archived ({archivedSessions.length})</span>
                  </div>
                  {archivedSectionOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </button>
                {archivedSectionOpen && (
                  <div className="space-y-0.5 mt-1">
                    {archivedSessions.map(renderSessionItem)}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Bottom Profile Footer */}
      <div className="p-3 border-t border-white/5 bg-[#171717] flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center text-white font-bold text-xs ring-1 ring-white/20">
            {user?.firstName ? user.firstName.charAt(0).toUpperCase() : 'E'}
          </div>
          <div className="min-w-0">
            <div className="text-xs font-semibold text-white truncate">
              {user?.firstName && user?.lastName ? `${user.firstName} ${user.lastName}` : user?.email || 'Engineering Lead'}
            </div>
            <div className="text-[10px] text-zinc-400 flex items-center gap-1 font-mono">
              <span>Pro Plan</span>
              <span>•</span>
              <span className="text-emerald-400">Online</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

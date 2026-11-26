import React, { useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  UploadCloud,
  CheckSquare,
  Network,
  MessageSquareCode,
  ShieldAlert,
  Download,
  Settings,
  HelpCircle,
  ArrowLeft,
  Workflow,
  Sparkles,
} from 'lucide-react';
import { PIDHelpModal } from './PIDHelpModal';
import { PIDSettingsModal } from './PIDSettingsModal';

interface PIDStudioLayoutProps {
  children: React.ReactNode;
  isFlush?: boolean;
  noHeader?: boolean;
}

export function PIDStudioLayout({ children, isFlush = false, noHeader = false }: PIDStudioLayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();

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

  return (
    <div className="flex flex-col h-screen w-full bg-background text-foreground overflow-hidden">
      {/* P&ID Studio Top Nav Shell (hidden when noHeader is true) */}
      {!noHeader && (
        <>
          <header className="flex h-14 items-center justify-between border-b border-white/10 bg-[#0d0d0d] text-zinc-100 px-4 backdrop-blur-md z-30 shrink-0 select-none">
            {/* Left: Branding & Solution Title */}
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => navigate('/solution')}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-white/10 bg-[#171717] hover:bg-white/10 text-xs font-medium text-zinc-400 hover:text-white transition-colors shadow-xs"
                title="Go to Solutions"
              >
                <ArrowLeft size={13} />
                <span className="hidden sm:inline">Solutions</span>
              </button>

              <div className="h-4 w-[1px] bg-white/10" />

              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-primary/20 border border-primary/30 flex items-center justify-center text-primary">
                  <Workflow size={14} />
                </div>
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-zinc-100 truncate max-w-[200px] sm:max-w-xs">
                    {solutionTitle}
                  </span>
                  <span className="text-[10px] text-zinc-400">P&ID Engineering Studio</span>
                </div>
              </div>
            </div>

            {/* Center: Tabs */}
            <nav className="hidden lg:flex items-center gap-1 p-1 rounded-xl bg-[#171717] border border-white/10 shadow-xs">
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
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      isActive
                        ? 'bg-white/15 text-white font-semibold border border-white/10 shadow-xs'
                        : 'text-zinc-400 hover:text-white hover:bg-white/5'
                    }`}
                  >
                    <Icon size={13} />
                    <span>{tab.label}</span>
                  </NavLink>
                );
              })}
            </nav>

            {/* Right: Actions & Tools */}
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setHelpOpen(true)}
                className="p-2 rounded-lg border border-white/10 bg-[#171717] hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
                title="Shortcuts & Cheatsheet"
              >
                <HelpCircle size={14} />
              </button>

              <button
                type="button"
                onClick={() => setSettingsOpen(true)}
                className="p-2 rounded-lg border border-white/10 bg-[#171717] hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
                title="AI Engine Settings"
              >
                <Settings size={14} />
              </button>
            </div>
          </header>

          {/* Mobile/Tablet Sub-Tab Strip */}
          <div className="lg:hidden flex items-center gap-1 px-3 py-1.5 border-b border-white/10 bg-[#141414] overflow-x-auto text-xs shrink-0 custom-scrollbar">
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
        </>
      )}

      {/* Main Viewport */}
      <main className={`flex-1 min-h-0 overflow-hidden ${isFlush ? 'p-0' : 'overflow-y-auto'}`}>
        {children}
      </main>

      {/* Modals */}
      <PIDHelpModal isOpen={helpOpen} onClose={() => setHelpOpen(false)} />
      <PIDSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

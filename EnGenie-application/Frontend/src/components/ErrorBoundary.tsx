import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[ErrorBoundary caught an error]:', error, errorInfo);
    this.setState({ errorInfo });
  }

  private handleReload = () => {
    window.location.reload();
  };

  private handleGoHome = () => {
    window.location.href = '/';
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen w-full flex-col items-center justify-center bg-[#0d0d0d] text-zinc-100 p-6 select-none font-sans">
          <div className="max-w-md w-full bg-[#171717] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center text-center">
            <div className="w-12 h-12 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 mb-4 shadow-lg shadow-rose-950/40">
              <AlertTriangle size={24} />
            </div>

            <h2 className="text-lg font-bold text-white mb-2">Something went wrong</h2>
            <p className="text-xs text-zinc-400 mb-4 leading-relaxed">
              An unexpected error occurred while rendering this interface.
            </p>

            {this.state.error && (
              <div className="w-full bg-[#101010] border border-white/5 rounded-xl p-3 mb-6 text-left overflow-auto max-h-36">
                <span className="text-[11px] font-mono text-rose-400 block break-words">
                  {this.state.error.message || String(this.state.error)}
                </span>
              </div>
            )}

            <div className="flex items-center gap-3 w-full">
              <button
                type="button"
                onClick={this.handleGoHome}
                className="flex-1 py-2 px-3 rounded-xl border border-white/10 bg-[#212121] hover:bg-white/10 text-xs font-medium text-zinc-300 hover:text-white transition-all flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <Home size={14} />
                <span>Home</span>
              </button>
              <button
                type="button"
                onClick={this.handleReload}
                className="flex-1 py-2 px-3 rounded-xl bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white shadow-md transition-all flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <RefreshCw size={14} />
                <span>Reload</span>
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

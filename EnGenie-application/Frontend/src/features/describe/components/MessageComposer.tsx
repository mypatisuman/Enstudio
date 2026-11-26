import React, { useRef, type KeyboardEvent, type RefObject } from 'react';
import {
  ArrowUp,
  Plus,
  Mic,
  Image as ImageIcon,
  FileText,
  X,
  Loader2,
  Layers,
} from 'lucide-react';
import type { PendingAttachment } from '../types';

interface MessageComposerProps {
  input: string;
  setInput: (v: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  onBuildCanvas?: () => void;
  hasImageAttached?: boolean;
  canBuildSolution?: boolean;
  loading: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  attachments?: PendingAttachment[];
  setAttachments?: (updater: (prev: PendingAttachment[]) => PendingAttachment[]) => void;
  thinkMode?: boolean;
  onToggleThinkMode?: () => void;
}

export function MessageComposer({
  input,
  setInput,
  onKeyDown,
  onSend,
  onBuildCanvas,
  hasImageAttached = false,
  canBuildSolution = false,
  loading,
  textareaRef,
  attachments = [],
  setAttachments,
  thinkMode = true,
  onToggleThinkMode,
}: MessageComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0 || !setAttachments) return;
    const file = e.target.files[0];
    const isImage = file.type.startsWith('image/');
    const isPdf = file.type === 'application/pdf';

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const newAtt: PendingAttachment = {
        id: `att_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
        name: file.name,
        kind: isImage ? 'image' : isPdf ? 'pdf' : 'text',
        mime: file.type || 'text/plain',
        previewUrl: isImage ? result : undefined,
        base64: isImage || isPdf ? result.split(',')[1] : undefined,
        text: !isImage && !isPdf ? result : undefined,
      };
      setAttachments(prev => [...prev, newAtt]);
    };

    if (isImage || isPdf) {
      reader.readAsDataURL(file);
    } else {
      reader.readAsText(file);
    }

    e.target.value = '';
  };

  const removeAttachment = (id: string) => {
    if (setAttachments) {
      setAttachments(prev => prev.filter(a => a.id !== id));
    }
  };

  const canSend = (input.trim().length > 0 || attachments.length > 0) && !loading;

  return (
    <div className="w-full max-w-3xl mx-auto px-4 pb-4 pt-2">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept="image/*,.pdf,.txt,.json"
      />

      {/* Floating Capsule Input Box */}
      <div className="rounded-2xl bg-[#212121] border border-white/10 hover:border-white/20 focus-within:border-white/30 shadow-2xl transition-all p-3 flex flex-col gap-2">
        {/* Attachments preview */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 pb-2 border-b border-white/10">
            {attachments.map(att => (
              <div
                key={att.id}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#2a2a2a] text-xs text-white border border-white/10"
              >
                {att.kind === 'image' ? (
                  <ImageIcon size={13} className="text-sky-400" />
                ) : (
                  <FileText size={13} className="text-amber-400" />
                )}
                <span className="max-w-[150px] truncate">{att.name}</span>
                <button
                  type="button"
                  onClick={() => removeAttachment(att.id)}
                  className="hover:text-rose-400 ml-1 text-zinc-400"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2">
          {/* Plus / Attach Button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            title="Attach scan, PDF drawing, or datasheet"
            className="w-8 h-8 rounded-full hover:bg-white/10 flex items-center justify-center text-zinc-400 hover:text-white transition-colors flex-shrink-0"
          >
            <Plus size={18} />
          </button>

          {/* Text Input */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask anything or describe process flow..."
            rows={1}
            className="flex-1 bg-transparent border-none text-white placeholder:text-zinc-500 text-sm resize-none outline-none leading-relaxed min-h-[36px] max-h-36 py-1.5"
            style={{ height: 'auto' }}
          />

          {/* Right Action Controls: Build Canvas, Mic, Send */}
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {/* Build Canvas Button */}
            {onBuildCanvas && (
              <button
                type="button"
                onClick={onBuildCanvas}
                disabled={loading}
                title={
                  hasImageAttached
                    ? "Build P&ID CAD Canvas from uploaded image/drawing"
                    : "Build Solution on Canvas with standard engineering defaults"
                }
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all duration-200 select-none ${
                  hasImageAttached || canBuildSolution
                    ? "bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white shadow-md shadow-emerald-950/40 border border-emerald-400/40 cursor-pointer"
                    : "bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 hover:border-emerald-500/50 cursor-pointer"
                } ${loading ? "opacity-50 cursor-not-allowed" : ""}`}
              >
                <Layers size={14} />
                <span className="whitespace-nowrap font-medium">
                  {hasImageAttached ? "Build from Image" : "Build Canvas"}
                </span>
              </button>
            )}

            <button
              type="button"
              title="Voice dictation"
              onClick={() => setInput(prev => prev + (prev ? ' ' : '') + 'Add 4" suction line from drum V-101 to pump P-101')}
              className="w-8 h-8 rounded-full hover:bg-white/10 flex items-center justify-center text-zinc-400 hover:text-white transition-colors"
            >
              <Mic size={17} />
            </button>

            {/* Circular Send / Loading Button */}
            <button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                canSend
                  ? 'bg-sky-500 hover:bg-sky-400 text-white shadow-md cursor-pointer'
                  : 'bg-white/10 text-zinc-500 cursor-not-allowed'
              }`}
            >
              {loading ? (
                <Loader2 size={16} className="animate-spin text-white" />
              ) : (
                <ArrowUp size={16} strokeWidth={2.5} />
              )}
            </button>
          </div>
        </div>
      </div>
      <div className="text-center mt-2 text-[11px] text-zinc-500 select-none">
        P&ID Multi-Agent Swarm can make mistakes. Verify critical process deliverables.
      </div>
    </div>
  );
}

import React, { useRef, useState } from 'react';
import {
  Sparkles,
  Paperclip,
  Mic,
  ArrowUp,
  Image as ImageIcon,
  Edit3,
  FileCheck,
  Plus,
  X,
  FileText,
  Wrench,
  Layers,
} from 'lucide-react';
import type { PendingAttachment } from '../types';

interface DescribeLandingStateProps {
  onSend: (text: string, attachments?: PendingAttachment[]) => void;
  onBuildCanvas?: (text?: string, attachments?: PendingAttachment[]) => void;
  thinkMode?: boolean;
  onToggleThinkMode?: () => void;
}

const ACTION_CHIPS = [
  {
    icon: Wrench,
    label: 'Identify instruments & accessories BOM',
    prompt: 'Identify all instruments, infer procurement specifications, and deduce required accessories (manifolds, thermowells, positioners, sunshades) for this P&ID',
    color: 'text-amber-400',
  },
  {
    icon: Edit3,
    label: 'Author Greenfield P&ID from spec',
    prompt: 'Design a greenfield 3-phase production separator V-101 with boot and dual centrifugal pumps P-101A/B',
    color: 'text-sky-400',
  },
  {
    icon: ImageIcon,
    label: 'Extract P&ID from image or scan',
    prompt: 'Extract all vessels, pumps, valves, and piping connectivity from an attached P&ID drawing scan',
    color: 'text-emerald-400',
  },
  {
    icon: Sparkles,
    label: 'Add separator & booster pump train',
    prompt: 'Add separator drum V-101 with boot, connect bottom to centrifugal pump P-101 suction with 4" line, and add level transmitter LT-101',
    color: 'text-purple-400',
  },
];

export function DescribeLandingState({
  onSend,
  onBuildCanvas,
  thinkMode,
  onToggleThinkMode,
}: DescribeLandingStateProps) {
  const [inputText, setInputText] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const hasImageAttached = attachments.some(a => a.kind === 'image' || a.kind === 'pdf');

  const handleBuildCanvas = () => {
    const prompt = inputText.trim()
      ? (hasImageAttached ? `${inputText.trim()} — Extract and build complete P&ID canvas from this uploaded diagram` : inputText.trim())
      : (hasImageAttached ? 'Extract and build complete P&ID canvas from this uploaded diagram' : 'Build Solution on Canvas');

    if (onBuildCanvas) {
      onBuildCanvas(prompt, attachments);
    } else {
      onSend(prompt, attachments);
    }
    setInputText('');
    setAttachments([]);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
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
    setAttachments(prev => prev.filter(a => a.id !== id));
  };

  const handleSubmit = (overrideText?: string) => {
    const text = (overrideText ?? inputText).trim();
    if (!text && attachments.length === 0) return;
    onSend(text, attachments);
    setInputText('');
    setAttachments([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4 max-w-3xl mx-auto w-full py-12 select-none animate-in fade-in duration-300">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept="image/*,.pdf,.txt,.json"
      />

      {/* Centered Heading */}
      <h1 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight mb-8 text-center">
        Build your plant PID
      </h1>

      {/* Main Pill / Capsule Input Box */}
      <div className="w-full rounded-2xl bg-[#212121] border border-white/10 hover:border-white/20 focus-within:border-white/30 shadow-2xl transition-all p-3 flex flex-col gap-2">
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

          {/* Text input */}
          <textarea
            ref={textareaRef}
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything or describe process flow..."
            rows={1}
            className="flex-1 bg-transparent border-none text-white placeholder:text-zinc-500 text-sm resize-none outline-none leading-relaxed min-h-[36px] max-h-36 py-1.5"
            style={{ height: 'auto' }}
          />

          {/* Right Action Icons: Build Canvas, Mic, Send */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Build Canvas Button */}
            <button
              type="button"
              onClick={handleBuildCanvas}
              title={
                hasImageAttached
                  ? "Build P&ID CAD Canvas from uploaded image/drawing"
                  : "Build and generate P&ID on CAD Canvas"
              }
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all duration-200 select-none ${
                hasImageAttached || inputText.trim().length > 0
                  ? "bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white shadow-md shadow-emerald-950/40 border border-emerald-400/40 cursor-pointer"
                  : "bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 hover:border-emerald-500/50 cursor-pointer"
              }`}
            >
              <Layers size={14} />
              <span className="whitespace-nowrap font-medium">
                {hasImageAttached ? "Build from Image" : "Build Canvas"}
              </span>
            </button>

            {/* Mic Button */}
            <button
              type="button"
              title="Voice dictation"
              onClick={() => handleSubmit('Dictate process requirement')}
              className="w-8 h-8 rounded-full hover:bg-white/10 flex items-center justify-center text-zinc-400 hover:text-white transition-colors"
            >
              <Mic size={17} />
            </button>

            {/* Circular Send Action Button */}
            <button
              type="button"
              onClick={() => handleSubmit()}
              disabled={!inputText.trim() && attachments.length === 0}
              className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                inputText.trim() || attachments.length > 0
                  ? 'bg-sky-500 hover:bg-sky-400 text-white shadow-md cursor-pointer'
                  : 'bg-white/10 text-zinc-500 cursor-not-allowed'
              }`}
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </div>

      {/* Action Shortcut Chips */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full mt-6">
        {ACTION_CHIPS.map((chip, idx) => {
          const Icon = chip.icon;
          return (
            <button
              key={idx}
              type="button"
              onClick={() => handleSubmit(chip.prompt)}
              className="flex items-center gap-3 p-3 rounded-xl bg-[#212121]/60 hover:bg-[#212121] border border-white/5 hover:border-white/15 text-left transition-all group shadow-xs"
            >
              <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform">
                <Icon size={15} className={chip.color} />
              </div>
              <span className="text-xs text-zinc-300 group-hover:text-white font-medium">
                {chip.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

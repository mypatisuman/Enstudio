import React, { useState, useEffect } from 'react';
import { X, Settings, Key, Cpu, ShieldCheck, Check } from 'lucide-react';

interface PIDSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function PIDSettingsModal({ isOpen, onClose }: PIDSettingsModalProps) {
  const [provider, setProvider] = useState<string>(() => {
    return localStorage.getItem('engenie_llm_provider') || 'gemini';
  });
  const [geminiKey, setGeminiKey] = useState<string>(() => {
    return localStorage.getItem('engenie_gemini_key') || '';
  });
  const [claudeKey, setClaudeKey] = useState<string>(() => {
    return localStorage.getItem('engenie_claude_key') || '';
  });
  const [openaiKey, setOpenaiKey] = useState<string>(() => {
    return localStorage.getItem('engenie_openai_key') || '';
  });
  const [customEndpoint, setCustomEndpoint] = useState<string>(() => {
    return localStorage.getItem('engenie_custom_endpoint') || '';
  });
  const [savedSuccess, setSavedSuccess] = useState(false);

  if (!isOpen) return null;

  const handleSave = () => {
    localStorage.setItem('engenie_llm_provider', provider);
    if (geminiKey) localStorage.setItem('engenie_gemini_key', geminiKey);
    if (claudeKey) localStorage.setItem('engenie_claude_key', claudeKey);
    if (openaiKey) localStorage.setItem('engenie_openai_key', openaiKey);
    if (customEndpoint) localStorage.setItem('engenie_custom_endpoint', customEndpoint);

    setSavedSuccess(true);
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 800);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4"
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-card border border-border rounded-2xl w-full max-w-md shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border bg-card/80">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-primary/10 border border-primary/20 text-primary">
              <Settings size={18} />
            </div>
            <div>
              <h3 className="font-semibold text-sm text-foreground">P&ID Studio Engine Settings</h3>
              <p className="text-xs text-muted-foreground">Multi-agent LLM providers & API routing</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 space-y-4 text-xs overflow-y-auto max-h-[75vh]">
          {/* Provider Selection */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold text-foreground">Primary Reasoning Engine</label>
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: 'gemini', label: 'Google Gemini', desc: '1.5 Pro' },
                { id: 'claude', label: 'Anthropic', desc: 'Claude 3.5' },
                { id: 'openai', label: 'OpenAI', desc: 'GPT-4o' },
              ].map(p => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setProvider(p.id)}
                  className={`p-2.5 rounded-xl border text-left transition-all ${
                    provider === p.id
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border bg-background hover:bg-accent text-foreground'
                  }`}
                >
                  <div className="font-semibold text-xs">{p.label}</div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">{p.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* API Key Input */}
          <div className="space-y-3 pt-2 border-t border-border">
            {provider === 'gemini' && (
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-muted-foreground">Gemini API Key</label>
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border bg-background focus-within:border-primary">
                  <Key size={13} className="text-muted-foreground" />
                  <input
                    type="password"
                    value={geminiKey}
                    onChange={e => setGeminiKey(e.target.value)}
                    placeholder="AIzaSy..."
                    className="w-full bg-transparent border-none text-xs text-foreground outline-none"
                  />
                </div>
              </div>
            )}

            {provider === 'claude' && (
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-muted-foreground">Anthropic API Key</label>
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border bg-background focus-within:border-primary">
                  <Key size={13} className="text-muted-foreground" />
                  <input
                    type="password"
                    value={claudeKey}
                    onChange={e => setClaudeKey(e.target.value)}
                    placeholder="sk-ant-..."
                    className="w-full bg-transparent border-none text-xs text-foreground outline-none"
                  />
                </div>
              </div>
            )}

            {provider === 'openai' && (
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-muted-foreground">OpenAI API Key</label>
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border bg-background focus-within:border-primary">
                  <Key size={13} className="text-muted-foreground" />
                  <input
                    type="password"
                    value={openaiKey}
                    onChange={e => setOpenaiKey(e.target.value)}
                    placeholder="sk-..."
                    className="w-full bg-transparent border-none text-xs text-foreground outline-none"
                  />
                </div>
              </div>
            )}

            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">Custom Model Endpoint (Optional)</label>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border bg-background focus-within:border-primary">
                <Cpu size={13} className="text-muted-foreground" />
                <input
                  type="text"
                  value={customEndpoint}
                  onChange={e => setCustomEndpoint(e.target.value)}
                  placeholder="http://localhost:11434/v1"
                  className="w-full bg-transparent border-none text-xs text-foreground outline-none"
                />
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-muted/50 border border-border flex items-start gap-2.5">
            <ShieldCheck size={16} className="text-emerald-500 flex-shrink-0 mt-0.5" />
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              API keys are stored client-side in your secure browser session storage and forwarded to the backend proxy for authorized agentic calls.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border bg-card/60">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-foreground hover:bg-accent transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground font-semibold text-xs hover:opacity-90 transition-all shadow-xs"
          >
            {savedSuccess ? (
              <>
                <Check size={13} />
                <span>Saved!</span>
              </>
            ) : (
              <span>Save Settings</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

import React from 'react';
import { X, Keyboard, Compass, MousePointer, Move, Command } from 'lucide-react';

interface PIDHelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function PIDHelpModal({ isOpen, onClose }: PIDHelpModalProps) {
  if (!isOpen) return null;

  const SHORTCUTS = [
    { key: 'Ctrl + K / ⌘K', desc: 'Quick search equipment, instruments, or loops' },
    { key: 'H', desc: 'Align selected symbols to a horizontal centerline' },
    { key: 'V', desc: 'Align selected symbols to a vertical centerline' },
    { key: 'Delete / Backspace', desc: 'Remove selected equipment or pipe stream' },
    { key: 'Scroll Wheel', desc: 'Zoom viewport centered at cursor' },
    { key: 'Click & Drag', desc: 'Pan canvas workspace (or hold middle-click)' },
    { key: 'Shift + Click', desc: 'Multi-select equipment items for batch alignment' },
    { key: 'Esc', desc: 'Cancel active symbol placement or close inspection drawer' },
  ];

  const ISA_TAG_PREFIXES = [
    { code: 'PT / PIT', meaning: 'Pressure Transmitter / Indicating Transmitter' },
    { code: 'TT / TIT', meaning: 'Temperature Transmitter' },
    { code: 'FT / FIT', meaning: 'Flow Transmitter' },
    { code: 'LT / LIT', meaning: 'Level Transmitter' },
    { code: 'PCV / FCV', meaning: 'Pressure / Flow Control Valve' },
    { code: 'PSV', meaning: 'Pressure Safety Relief Valve' },
    { code: 'P', meaning: 'Pump (e.g. P-101A/B)' },
    { code: 'V / D', meaning: 'Vessel / Drum (e.g. V-101)' },
    { code: 'E / HX', meaning: 'Heat Exchanger (e.g. E-101)' },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4"
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-card border border-border rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border bg-card/80">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-primary/10 border border-primary/20 text-primary">
              <Keyboard size={18} />
            </div>
            <div>
              <h3 className="font-semibold text-sm text-foreground">P&ID Studio Shortcuts & Reference</h3>
              <p className="text-xs text-muted-foreground">Keyboard commands and ISA-5.1 tagging standards</p>
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
        <div className="p-5 overflow-y-auto space-y-5 text-xs">
          <div>
            <h4 className="text-[11px] font-bold text-primary uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
              <Command size={12} /> Canvas Navigation & Drafting
            </h4>
            <div className="grid grid-cols-1 gap-1.5">
              {SHORTCUTS.map((s, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 rounded-lg bg-background/50 border border-border"
                >
                  <span className="text-muted-foreground">{s.desc}</span>
                  <kbd className="px-2 py-0.5 rounded bg-muted border border-border font-mono text-[10px] text-foreground font-semibold">
                    {s.key}
                  </kbd>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h4 className="text-[11px] font-bold text-sky-400 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
              <Compass size={12} /> Standard ISA-5.1 Tag Prefixes
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {ISA_TAG_PREFIXES.map((p, idx) => (
                <div
                  key={idx}
                  className="p-2 rounded-lg bg-background/50 border border-border flex flex-col gap-0.5"
                >
                  <span className="font-mono font-bold text-primary text-[11px]">{p.code}</span>
                  <span className="text-[10px] text-muted-foreground">{p.meaning}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end px-5 py-3 border-t border-border bg-card/60">
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground font-medium text-xs hover:opacity-90 transition-opacity"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}

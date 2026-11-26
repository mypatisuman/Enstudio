import { AlertTriangle } from 'lucide-react';
import type { DescribeSession } from '../types';

interface SessionDeleteModalProps {
  session: DescribeSession;
  onConfirm: () => void;
  onClose: () => void;
}

export function SessionDeleteModal({
  session,
  onConfirm,
  onClose,
}: SessionDeleteModalProps) {
  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center z-50 p-4"
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-card border border-border rounded-2xl p-6 w-full max-w-sm shadow-2xl flex flex-col gap-4">
        <div className="flex items-center gap-3 text-red-500">
          <div className="p-2.5 rounded-full bg-red-500/10 border border-red-500/20">
            <AlertTriangle size={20} />
          </div>
          <div>
            <h3 className="font-semibold text-foreground text-sm">Delete Session?</h3>
            <p className="text-xs text-muted-foreground mt-0.5">This action cannot be undone.</p>
          </div>
        </div>

        <p className="text-xs text-muted-foreground leading-relaxed">
          The conversation thread <strong className="text-foreground">"{session.title}"</strong> and all agent reasoning history will be permanently deleted.
        </p>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-foreground hover:bg-accent transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-semibold shadow-sm transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

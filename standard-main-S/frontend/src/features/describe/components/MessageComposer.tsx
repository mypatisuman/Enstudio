import { useState } from 'react'
import type { RefObject, KeyboardEvent } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { toast } from 'sonner'
import { SendHorizonal, Mic, Square, Paperclip, Image as ImageIcon, FileText, X } from 'lucide-react'
import { Spinner } from '../../../shared/components/spinner/Spinner'
import { useVoiceInput } from '../hooks/useVoiceInput'
import { ATTACHMENT_EXTENSIONS } from '../attachments/classify'
import { loadAttachment } from '../attachments/loadAttachment'
import type { PendingAttachment } from '../attachments/types'

function AttachmentIcon({ kind }: { kind: PendingAttachment['kind'] }) {
  return kind === 'image' ? <ImageIcon size={13} /> : <FileText size={13} />
}

export function MessageComposer({
  input, setInput, onKeyDown, onSend, loading, textareaRef, attachments, setAttachments,
}: {
  input: string
  setInput: (v: string) => void
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void
  onSend: () => void
  loading: boolean
  textareaRef: RefObject<HTMLTextAreaElement | null>
  attachments: PendingAttachment[]
  setAttachments: (updater: (prev: PendingAttachment[]) => PendingAttachment[]) => void
}) {
  // Voice dictation — mic only renders when the runtime actually supports it
  // (see useVoiceInput; WebView2 often doesn't), so it never shows a control
  // that's guaranteed to fail.
  const voice = useVoiceInput(setInput)
  const [attaching, setAttaching] = useState(false)

  async function handleAttach() {
    const path = await open({ multiple: false, directory: false, filters: [{ name: 'Attachments', extensions: ATTACHMENT_EXTENSIONS }] })
    if (typeof path !== 'string') return
    setAttaching(true)
    try {
      const att = await loadAttachment(path)
      setAttachments(prev => [...prev, att])
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setAttaching(false)
    }
  }

  function removeAttachment(id: string) {
    setAttachments(prev => prev.filter(a => a.id !== id))
  }

  return (
    <div style={{
      flexShrink: 0,
      background: 'var(--bg-primary)',
      padding: '24px', display: 'flex', justifyContent: 'center'
    }}>
      <div style={{
        display: 'flex', flexDirection: 'column', width: '100%', maxWidth: 840,
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 12,
        boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
        transition: 'border-color 0.2s',
      }}
      onFocus={e => e.currentTarget.style.borderColor = 'var(--accent)'}
      onBlur={e => e.currentTarget.style.borderColor = 'var(--border)'}
      >
        {attachments.length > 0 && (
          <div className="desc-attach-row">
            {attachments.map(a => (
              <span key={a.id} className="desc-attach-chip">
                <AttachmentIcon kind={a.kind} />
                <span className="desc-attach-name">{a.name}</span>
                <button type="button" onClick={() => removeAttachment(a.id)} title="Remove"><X size={12} /></button>
              </span>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Describe equipment, ask a question, or give instructions..."
          rows={3}
          style={{
            width: '100%', background: 'transparent', border: 'none',
            color: 'var(--text-primary)', font: 'inherit', fontSize: 14,
            padding: '16px', resize: 'none', outline: 'none', lineHeight: 1.5,
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px 8px 16px' }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {voice.listening
              ? <span style={{ color: 'var(--danger)' }}>● Listening…</span>
              : <>Press <strong>Enter</strong> to send, <strong>Shift+Enter</strong> for newline</>}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <button
              type="button"
              className="btn btn-ghost tip"
              data-tip="Attach image, PDF, docx, or text"
              style={{ padding: '6px 8px', borderRadius: 8, color: 'var(--text-muted)' }}
              onClick={handleAttach}
              disabled={attaching}
            >
              {attaching ? <Spinner size={13} /> : <Paperclip size={15} />}
            </button>
            {voice.supported && (
              <button
                type="button"
                className="btn btn-ghost tip"
                data-tip={voice.listening ? 'Stop dictation' : 'Voice input'}
                style={{
                  padding: '6px 8px', borderRadius: 8,
                  color: voice.listening ? 'var(--danger)' : 'var(--text-muted)',
                }}
                onClick={() => (voice.listening ? voice.stop() : voice.start(input))}
              >
                {voice.listening ? <Square size={14} fill="currentColor" /> : <Mic size={15} />}
              </button>
            )}
            <button
              className="btn btn-primary"
              style={{ padding: '6px 14px', fontSize: 13, borderRadius: 8, opacity: ((!input.trim() && attachments.length === 0) || loading) ? 0.5 : 1 }}
              disabled={(!input.trim() && attachments.length === 0) || loading}
              onClick={onSend}
            >
              {loading ? <Spinner size={13} /> : (
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                  Send <SendHorizonal size={13} strokeWidth={2} />
                </span>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

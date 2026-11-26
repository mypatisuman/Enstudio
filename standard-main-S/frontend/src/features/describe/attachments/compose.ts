import type { ApiContentPart } from '../utils/llmClient'
import type { PendingAttachment } from './types'

export interface ComposedMessage {
  text: string                    // persisted display/apiContent text — includes inlined text/docx content + attachment notes, never binary
  parts: ApiContentPart[] | null   // non-null only when an image/PDF is attached — the actual content sent for THIS turn
  attachmentSummary: { name: string; kind: string }[]
}

/**
 * Folds attachments into one outgoing message. Text/docx attachments are
 * inlined as plain text (so they're just... more text, no wire-format change,
 * and safe to persist). Image/PDF attachments become real vision/document
 * content parts for THIS request only — never persisted as binary, so the
 * database and future turns never carry base64.
 */
export function composeWithAttachments(userText: string, attachments: PendingAttachment[]): ComposedMessage {
  let text = userText
  const attachmentSummary = attachments.map(a => ({ name: a.name, kind: a.kind }))

  for (const a of attachments) {
    if (a.kind === 'text' || a.kind === 'docx') {
      text += `\n\n--- Attached: ${a.name} ---\n${a.text ?? ''}`
    } else {
      text += `\n\n[Attached ${a.kind}: ${a.name}]`
    }
  }

  const visual = attachments.filter((a): a is PendingAttachment & { base64: string } => (a.kind === 'image' || a.kind === 'pdf') && !!a.base64)
  const parts: ApiContentPart[] | null = visual.length
    ? [
        { type: 'text', text },
        ...visual.map((a): ApiContentPart => (
          a.kind === 'image'
            ? { type: 'image', mediaType: a.mime, data: a.base64 }
            : { type: 'document', mediaType: a.mime, data: a.base64 }
        )),
      ]
    : null

  return { text, parts, attachmentSummary }
}

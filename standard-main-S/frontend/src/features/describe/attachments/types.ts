// One attached file, fully loaded and ready to send. `previewUrl` is only set
// for images (chat bubble thumbnail). `text` holds already-extracted text for
// text/docx kinds — the LLM sees this inlined into the message, never a binary
// blob, for those two kinds. `base64`/`mime` are only used for image/pdf, which
// go to the provider as real vision/document content blocks.
export type AttachmentKind = 'image' | 'pdf' | 'text' | 'docx'

export interface PendingAttachment {
  id: string
  name: string
  kind: AttachmentKind
  mime: string
  base64?: string      // image / pdf only
  text?: string        // text / docx only (already extracted)
  previewUrl?: string  // image only
}

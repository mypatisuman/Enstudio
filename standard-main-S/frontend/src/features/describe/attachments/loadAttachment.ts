import * as mammoth from 'mammoth'
import { readAttachment } from '../../../services/describe'
import { classifyExt } from './classify'
import type { PendingAttachment } from './types'

// Uint8Array<ArrayBuffer>, not bare Uint8Array — the bare annotation widens
// .buffer to ArrayBufferLike, which mammoth's arrayBuffer param rejects.
function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes
}

let seq = 0

/**
 * Read a user-picked file and turn it into a ready-to-send attachment.
 * Images/PDF keep their base64 (sent as real vision/document content to the
 * LLM); text/docx are converted to plain text right here (sent as text — no
 * binary ever reaches the LLM for those two kinds). Throws with a message
 * suitable to show the user directly (unsupported format, oversized file, etc).
 */
export async function loadAttachment(filePath: string): Promise<PendingAttachment> {
  const raw = await readAttachment(filePath)
  const cls = classifyExt(raw.ext)
  if (!cls) {
    throw new Error(`".${raw.ext || '?'}" isn't supported. Try an image, PDF, .docx, or a plain text file.`)
  }

  const id = `att${Date.now()}_${seq++}`
  const base: Pick<PendingAttachment, 'id' | 'name' | 'kind' | 'mime'> = {
    id, name: raw.name, kind: cls.kind, mime: cls.mime,
  }

  if (cls.kind === 'image') {
    return { ...base, base64: raw.data, previewUrl: `data:${cls.mime};base64,${raw.data}` }
  }
  if (cls.kind === 'pdf') {
    return { ...base, base64: raw.data }
  }
  if (cls.kind === 'text') {
    const text = new TextDecoder('utf-8').decode(base64ToBytes(raw.data))
    return { ...base, text }
  }
  // docx
  const bytes = base64ToBytes(raw.data)
  const result = await mammoth.extractRawText({ arrayBuffer: bytes.buffer })
  return { ...base, text: result.value }
}

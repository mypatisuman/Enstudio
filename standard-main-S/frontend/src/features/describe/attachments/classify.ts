import type { AttachmentKind } from './types'

const IMAGE_MIME: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
}
const TEXT_EXT = new Set(['txt', 'md', 'csv', 'json', 'yml', 'yaml', 'log'])

// File-picker filter — only extensions this module can actually turn into
// something an LLM can use. Legacy .doc (binary Word 97-2003) is deliberately
// excluded: parsing it needs much heavier tooling than mammoth (docx-only) and
// isn't worth it for a legacy format.
export const ATTACHMENT_EXTENSIONS = [
  ...Object.keys(IMAGE_MIME), 'pdf', ...TEXT_EXT, 'docx',
]

export interface Classification { kind: AttachmentKind; mime: string }

/** Returns null for a format this feature doesn't support (e.g. legacy .doc). */
export function classifyExt(ext: string): Classification | null {
  const e = ext.toLowerCase()
  if (IMAGE_MIME[e]) return { kind: 'image', mime: IMAGE_MIME[e] }
  if (e === 'pdf') return { kind: 'pdf', mime: 'application/pdf' }
  if (e === 'docx') return { kind: 'docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }
  if (TEXT_EXT.has(e)) return { kind: 'text', mime: 'text/plain' }
  return null
}

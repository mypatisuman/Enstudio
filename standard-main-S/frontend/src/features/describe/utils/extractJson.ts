import type { ClaudeResponse } from '../types'

export function extractJson(raw: string): ClaudeResponse | null {
  // Strip markdown fences if present
  const stripped = raw.replace(/^```(?:json)?\s*/m, '').replace(/\s*```\s*$/m, '').trim()
  // Find first { ... } block
  const start = stripped.indexOf('{')
  const end   = stripped.lastIndexOf('}')
  if (start === -1 || end === -1) return null
  try { return JSON.parse(stripped.slice(start, end + 1)) }
  catch { return null }
}

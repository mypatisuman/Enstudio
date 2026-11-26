// Cache for real Canvas-screen thumbnails (captured via CanvasThumbnailCapture).
// Keyed by project id; invalidated when the project's last_extraction changes,
// so a re-extraction produces a fresh thumbnail instead of showing a stale one.

// v2 — bumped so any thumbnail captured before the "cached but never loaded
// into state" bug fix (and the earlier wrong-background-color bug) is never
// read back; those runs start clean under a new namespace instead.
const STORAGE_PREFIX = 'enstudio:thumb:v2:'

interface CacheEntry {
  dataUrl: string
  lastExtraction: string | null
}

const mem = new Map<string, CacheEntry>()
// pids we've already tried and got nothing useful from (empty graph, capture
// failure) — avoids re-queuing them forever within this session.
const failed = new Set<string>()

function storageKey(pid: string) {
  return STORAGE_PREFIX + pid
}

export function getCachedThumb(pid: string, lastExtraction: string | null): string | null {
  const hit = mem.get(pid)
  if (hit && hit.lastExtraction === lastExtraction) return hit.dataUrl

  try {
    const raw = localStorage.getItem(storageKey(pid))
    if (!raw) return null
    const parsed: CacheEntry = JSON.parse(raw)
    if (parsed.lastExtraction !== lastExtraction) return null
    mem.set(pid, parsed)
    return parsed.dataUrl
  } catch {
    return null
  }
}

export function setCachedThumb(pid: string, lastExtraction: string | null, dataUrl: string) {
  const entry: CacheEntry = { dataUrl, lastExtraction }
  mem.set(pid, entry)
  try {
    localStorage.setItem(storageKey(pid), JSON.stringify(entry))
  } catch {
    // localStorage full or unavailable — in-memory cache still works for this session
  }
}

export function markFailed(pid: string) {
  failed.add(pid)
}

export function hasFailed(pid: string) {
  return failed.has(pid)
}

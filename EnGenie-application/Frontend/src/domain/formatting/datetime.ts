// Shared SQLite-timestamp parsing — SQLite's `datetime('now')` always
// produces "YYYY-MM-DD HH:MM:SS" in UTC with no timezone suffix. Both
// IngestScreen (formatDate) and UsageScreen (fmtTime) independently
// re-derived this same "append Z if there's no timezone marker already"
// conversion before this extraction; this is the one shared parsing step.
//
// NOTE: display formatting is intentionally NOT unified here — IngestScreen
// formats in the browser's local locale/timezone, UsageScreen formats fixed
// to 'Asia/Kolkata' with an 'en-IN' locale. That's a real, if easily
// overlooked, behavioral difference between the two screens (flagged during
// Phase 1's analysis). Per Phase 6's "preserve behavior exactly" rule, this
// extraction only removes the duplicated PARSING step; each caller keeps
// its own `.toLocaleString(...)` call and options exactly as before. Fixing
// the Asia/Kolkata-vs-local-timezone inconsistency is a deliberate follow-up
// decision, not something to bundle silently into a refactor.
export function parseSqliteUtc(ts: string): Date | null {
  if (!ts) return null
  const iso = ts.replace(' ', 'T')
  const withTz = /[Z+-]\d*$/.test(iso) ? iso : iso + 'Z'
  const d = new Date(withTz)
  return isNaN(d.getTime()) ? null : d
}

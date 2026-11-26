import { parseSqliteUtc } from '../../domain/formatting/datetime'

// Timestamps from the backend are UTC but may lack a timezone suffix.
// Normalise to ISO 8601 with Z so JS Date always interprets them as UTC,
// then toLocaleString() converts to the user's local timezone automatically.
export function fmtTime(ts: string): string {
  if (!ts) return '—'
  const d = parseSqliteUtc(ts)
  if (!d) return ts
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Kolkata',
  })
}

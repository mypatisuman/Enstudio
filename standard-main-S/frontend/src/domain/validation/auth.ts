// Mirrors auth rules in lib.rs so users get instant feedback instead of a
// round-trip error. The backend re-validates regardless — this is UX, not trust.
export function passwordProblem(pw: string): string | null {
  if (pw.length < 8)            return 'at least 8 characters'
  if (!/[A-Z]/.test(pw))        return 'one uppercase letter'
  if (!/[a-z]/.test(pw))        return 'one lowercase letter'
  if (!/[0-9]/.test(pw))        return 'one number'
  if (!/[^A-Za-z0-9]/.test(pw)) return 'one special character'
  return null
}

export function usernameProblem(u: string): string | null {
  const t = u.trim()
  if (t.length < 3)  return 'at least 3 characters'
  if (t.length > 32) return 'at most 32 characters'
  if (!/^[A-Za-z0-9._-]+$/.test(t)) return 'only letters, numbers, and . _ -'
  return null
}

// Mirrors valid_email() in commands/auth.rs. Kept in step with it — a looser
// regex here would let the field look fine and then fail on submit.
export const emailOk = (e: string) =>
  /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(e.trim())

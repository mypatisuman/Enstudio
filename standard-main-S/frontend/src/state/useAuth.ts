import { createContext, useContext } from 'react'
import type { AuthUser } from '../services/authApi'

export interface AuthCtxValue {
  user: AuthUser | null
  loading: boolean                 // true while restoring the session on startup
  // Adopts an already-authenticated user (callers do apiLogin/apiSignupFinalize
  // themselves so they can render their own field-level errors).
  login:  (user: AuthUser) => void
  updateProfile: (id: number, name: string, email: string) => Promise<void>
  logout: () => void
}

export const AuthCtx = createContext<AuthCtxValue | null>(null)

export function useAuth(): AuthCtxValue {
  const ctx = useContext(AuthCtx)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

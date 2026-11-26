import React, { useState, useEffect, useCallback } from 'react'
import {
  apiGetUser, apiUpdateUser, storedUserId, rememberUser, forgetUser, touchSession, type AuthUser,
} from '../services/authApi'
import { AuthCtx } from './useAuth'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  // Persistent login: revalidate the remembered user id against the DB. A stale
  // id (user deleted/deactivated) is dropped so we land on the login screen.
  useEffect(() => {
    const id = storedUserId()
    if (!id) { setLoading(false); return }
    apiGetUser(id)
      .then(setUser)
      .catch(() => forgetUser())
      .finally(() => setLoading(false))
  }, [])



  const login = useCallback((u: AuthUser) => {
    rememberUser(u.id)
    setUser(u)
  }, [])


  const logout = useCallback(() => {
    forgetUser()
    setUser(null)
  }, [])

  const updateProfile = useCallback(async (id: number, name: string, email: string) => {
    const u = await apiUpdateUser(id, name, email)
    setUser(u)
  }, [])

  // Auto-logout and session extension
  useEffect(() => {
    if (!user) return

    let lastTouch = Date.now()
    const handleActivity = () => {
      const now = Date.now()
      // Throttle localStorage updates to once per minute
      if (now - lastTouch > 60000) {
        touchSession()
        lastTouch = now
      }
    }

    window.addEventListener('mousemove', handleActivity, { passive: true })
    window.addEventListener('keydown', handleActivity, { passive: true })
    window.addEventListener('click', handleActivity, { passive: true })

    // Check expiration every minute
    const interval = setInterval(() => {
      // storedUserId() returns null if 20 mins have passed since LAST_ACTIVE_KEY
      if (!storedUserId()) {
        logout()
      }
    }, 60000)

    return () => {
      window.removeEventListener('mousemove', handleActivity)
      window.removeEventListener('keydown', handleActivity)
      window.removeEventListener('click', handleActivity)
      clearInterval(interval)
    }
  }, [user, logout])

  return (
    <AuthCtx.Provider value={{ user, loading, login, updateProfile, logout }}>
      {children}
    </AuthCtx.Provider>
  )
}

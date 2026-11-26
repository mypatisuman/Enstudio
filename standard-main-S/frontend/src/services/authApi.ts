// Auth client — native Tauri commands (see src-tauri/src/lib.rs), no server.
// Accounts live in studio.db; the app stays fully standalone (no Flask).
// "Stay logged in" = remember the user id locally and revalidate it on startup.

import * as auth from './invoke/auth'
import type { AuthUser } from './invoke/types'

export type { AuthUser }

const USER_ID_KEY = 'enstudio_uid'
const LAST_ACTIVE_KEY = 'enstudio_last_active'
const SESSION_TIMEOUT_MS = 20 * 60 * 1000 // 20 minutes

export function storedUserId(): number | null {
  const v = localStorage.getItem(USER_ID_KEY)
  if (!v) return null

  const lastActiveStr = localStorage.getItem(LAST_ACTIVE_KEY)
  if (lastActiveStr) {
    const lastActive = parseInt(lastActiveStr, 10)
    if (Date.now() - lastActive > SESSION_TIMEOUT_MS) {
      forgetUser()
      return null
    }
  }

  touchSession()
  return Number(v)
}

export function touchSession(): void {
  localStorage.setItem(LAST_ACTIVE_KEY, String(Date.now()))
}

export function rememberUser(id: number): void {
  localStorage.setItem(USER_ID_KEY, String(id))
  touchSession()
}

export function forgetUser(): void {
  localStorage.removeItem(USER_ID_KEY)
  localStorage.removeItem(LAST_ACTIVE_KEY)
}

// invoke rejects with the Rust Err(String), so callers get a plain string message.
export function apiSignupRequest(username: string, email: string): Promise<void> {
  return auth.signupRequest(username, email)
}
export function apiSignupVerifyOtp(email: string, otp: string): Promise<void> {
  return auth.signupVerifyOtp(email, otp)
}
export function apiSignupFinalize(email: string, otp: string, password: string): Promise<AuthUser> {
  return auth.signupFinalize(email, otp, password)
}
// Resolves if the address has no problem, rejects with the reason if it does.
export function apiCheckEmail(email: string): Promise<void> {
  return auth.checkEmail(email)
}
// Resolves if the username is free, rejects with the reason if not.
export function apiCheckUsername(username: string): Promise<void> {
  return auth.checkUsername(username)
}
// identifier = username OR email
export function apiLogin(identifier: string, password: string): Promise<AuthUser> {
  return auth.login(identifier, password)
}
export function apiGetUser(id: number): Promise<AuthUser> {
  return auth.getUser(id)
}
export function apiUpdateUser(id: number, name: string, email: string): Promise<AuthUser> {
  return auth.updateUser(id, name, email)
}
// Sends the password-reset OTP email. Always resolves — caller should show the
// same "check your inbox" message whether or not the email is registered.
export function apiForgotPassword(email: string): Promise<void> {
  return auth.forgotPassword(email)
}
export function apiVerifyOtp(email: string, otp: string): Promise<void> {
  return auth.verifyOtp(email, otp)
}
// Checks if the new password matches the old password without committing it.
export function apiCheckNewPassword(email: string, otp: string, newPassword: string): Promise<void> {
  return auth.checkNewPassword(email, otp, newPassword)
}
// Validates the OTP and updates the password.
export function apiResetPassword(email: string, otp: string, newPassword: string): Promise<void> {
  return auth.resetPassword(email, otp, newPassword)
}

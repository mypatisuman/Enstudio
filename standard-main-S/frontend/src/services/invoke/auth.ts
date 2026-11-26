// Typed invoke wrappers for src-tauri/src/commands/auth.rs — thin transport
// boundary only, no session/business logic (that lives in services/auth).

import { invoke } from '@tauri-apps/api/core'
import type { AuthUser } from './types'

export function signupRequest(username: string, email: string): Promise<void> {
  return invoke('signup_request', { username, email })
}

export function signupVerifyOtp(email: string, otp: string): Promise<void> {
  return invoke('signup_verify_otp', { email, otp })
}

export function signupFinalize(email: string, otp: string, password: string): Promise<AuthUser> {
  return invoke('signup_finalize', { email, otp, password })
}

/// Rejects with the reason the address is unusable; resolves when there is
/// none. Used for the inline hint on the signup form.
export function checkEmail(email: string): Promise<void> {
  return invoke('check_email', { email })
}

/// Rejects if the username is malformed or already taken; resolves otherwise.
export function checkUsername(username: string): Promise<void> {
  return invoke('check_username', { username })
}

export function login(identifier: string, password: string): Promise<AuthUser> {
  return invoke('login', { identifier, password })
}

export function getUser(id: number): Promise<AuthUser> {
  return invoke('get_user', { id })
}

export function updateUser(id: number, name: string, email: string): Promise<AuthUser> {
  return invoke('update_user', { id, name, email })
}

/// Requests a password-reset OTP be sent to the given email.
/// Always resolves (even for unknown emails) — prevents enumeration.
export async function forgotPassword(email: string): Promise<void> {
  return invoke('forgot_password', { email })
}

export async function verifyOtp(email: string, otp: string): Promise<void> {
  return invoke('verify_otp', { email, otp })
}

export async function checkNewPassword(email: string, otp: string, newPassword: string): Promise<void> {
  return invoke('check_new_password', { email, otp, newPassword })
}

export async function resetPassword(email: string, otp: string, newPassword: string): Promise<void> {
  return invoke('reset_password', { email, otp, newPassword })
}

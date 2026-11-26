import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, Check, Loader2, X, Mail, KeyRound, Lock } from 'lucide-react'
import { useAuth } from '../../state/useAuth'
import { passwordProblem, usernameProblem, emailOk } from '../../domain/validation/auth'
import { apiCheckEmail, apiCheckUsername, apiForgotPassword, apiVerifyOtp, apiCheckNewPassword, apiResetPassword, apiSignupRequest, apiSignupVerifyOtp, apiSignupFinalize, apiLogin } from '../../services/authApi'
import { PasswordInput } from '../../shared/components/input/PasswordInput'

// Verdict for a field validated by the backend when the user leaves it —
// one round trip per value entered, not one per keystroke.
type FieldCheck =
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'ok' }
  | { state: 'bad'; message: string }

/** Backend-check state for one field: the verdict, a runner, and a reset.
 *
 * `gate` is the local format test — no point asking the backend about a
 * half-typed value. The sequence counter drops a verdict that arrives after
 * the user has already edited the field again; without it a slow check on the
 * old value overwrites the result for the new one. */
function useFieldCheck(gate: (v: string) => boolean, api: (v: string) => Promise<void>) {
  const [check, setCheck] = useState<FieldCheck>({ state: 'idle' })
  const seq = useRef(0)

  function reset() {
    seq.current++
    setCheck({ state: 'idle' })
  }

  async function run(raw: string) {
    const value = raw.trim()
    if (!value || !gate(value)) { reset(); return }
    const mine = ++seq.current
    setCheck({ state: 'checking' })
    try {
      await api(value)
      if (mine === seq.current) setCheck({ state: 'ok' })
    } catch (err) {
      if (mine !== seq.current) return
      setCheck({
        state: 'bad',
        message: typeof err === 'string' ? err : 'Could not verify that value.',
      })
    }
  }

  return { check, run, reset }
}

/** Status badge shown inside a field on the right. */
function FieldStatus({ check, okTitle }: { check: FieldCheck; okTitle: string }) {
  if (check.state === 'checking') {
    return (
      <span className="auth-input-status" title="Checking…">
        <Loader2 size={15} className="notif-spin" />
      </span>
    )
  }
  if (check.state === 'ok') {
    return (
      <span className="auth-input-status auth-input-status--ok" title={okTitle}>
        <Check size={12} strokeWidth={3} />
      </span>
    )
  }
  if (check.state === 'bad') {
    return (
      <span className="auth-input-status auth-input-status--bad" title={check.message}>
        <AlertCircle size={15} />
      </span>
    )
  }
  return null
}

// ── Forgot Password Modal ──────────────────────────────────────────────────────

type ForgotStep = 'email' | 'otp' | 'newpass' | 'done'

function ForgotPasswordModal({ onClose }: {
  onClose: () => void
}) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<ForgotStep>('email')

  const [email, setEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [newPass, setNewPass] = useState('')
  const [confirmPass, setConfirmPass] = useState('')
  const [showNewPass, setShowNewPass] = useState(false)
  const [showConfirmPass, setShowConfirmPass] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const newPassCheck = useFieldCheck(
    v => !passwordProblem(v),
    v => apiCheckNewPassword(email.trim().toLowerCase(), otp.trim(), v)
  )

  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])

  function dismiss() {
    setOpen(false)
    setTimeout(onClose, 160)
  }

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') dismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  async function handleSendOtp(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const trimmed = email.trim().toLowerCase()
    if (!emailOk(trimmed)) {
      setError('Please enter a valid email address.')
      return
    }
    setBusy(true)
    try {
      await apiForgotPassword(trimmed)
      // Always move to OTP step — don't leak whether the email exists.
      setStep('otp')
    } catch (err) {
      setError(typeof err === 'string' ? err : err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  async function handleVerifyOtp(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (otp.trim().length !== 6 || !/^\d{6}$/.test(otp.trim())) {
      setError('Please enter the 6-digit code from your email.')
      return
    }
    setBusy(true)
    try {
      await apiVerifyOtp(email.trim().toLowerCase(), otp.trim())
      setStep('newpass')
    } catch (err) {
      setError(typeof err === 'string' ? err : err instanceof Error ? err.message : 'Invalid code.')
    } finally {
      setBusy(false)
    }
  }

  async function handleResetPassword(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const problem = passwordProblem(newPass)
    if (problem) { setError(`Password needs ${problem}.`); return }
    if (newPass !== confirmPass) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      // Reset the password in the DB.
      await apiResetPassword(email.trim().toLowerCase(), otp.trim(), newPass)
      setStep('done')
    } catch (err) {
      setError(typeof err === 'string' ? err : err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const stepIcon = {
    email:   <Mail size={22} strokeWidth={1.6} />,
    otp:     <KeyRound size={22} strokeWidth={1.6} />,
    newpass: <Lock size={22} strokeWidth={1.6} />,
    done:    <Check size={22} strokeWidth={2.5} />,
  }[step]

  const stepTitle = {
    email:   'Forgot password?',
    otp:     'Enter your code',
    newpass: 'Set new password',
    done:    'Password updated!',
  }[step]

  const stepSubtitle = {
    email:   `Enter your account email and we'll send you a reset code.`,
    otp:     `We sent a 6-digit code to ${email}. Enter it below.`,
    newpass: 'Choose a strong new password for your account.',
    done:    'Your password has been changed. You can now sign in.',
  }[step]

  return createPortal(
    <div
      className={`modal-backdrop forgot-pw-backdrop${open ? ' open' : ''}`}
      style={{
        position: 'fixed', inset: 0, zIndex: 10000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(5,10,20,0.72)', backdropFilter: 'blur(6px)',
      }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) dismiss() }}
    >
      <div
        className="modal-dialog forgot-pw-dialog"
        style={{
          position: 'relative',
          width: 380,
          background: 'var(--bg-glass)',
          backdropFilter: 'blur(18px)',
          WebkitBackdropFilter: 'blur(18px)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-xl)',
          boxShadow: 'var(--shadow-lg), var(--shadow-glow)',
          padding: '32px 28px 28px',
          display: 'flex',
          flexDirection: 'column',
          gap: 0,
        }}
      >
        {/* Close button */}
        <button
          className="modal-x"
          onClick={dismiss}
          aria-label="Close"
          style={{ position: 'absolute', top: 14, right: 14 }}
        >
          <X size={15} />
        </button>

        {/* Step icon + title */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 22, gap: 10 }}>
          <div style={{
            width: 46, height: 46, borderRadius: '50%',
            background: step === 'done' ? 'var(--success)' : 'var(--accent-dim, rgba(59,130,246,0.12))',
            color: step === 'done' ? '#fff' : 'var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1px solid',
            borderColor: step === 'done' ? 'var(--success)' : 'var(--accent-glow)',
            transition: 'all 0.2s ease',
          }}>
            {stepIcon}
          </div>
          <div style={{ textAlign: 'center' }}>
            <p style={{ margin: 0, fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>{stepTitle}</p>
            <p style={{ margin: '5px 0 0', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>{stepSubtitle}</p>
          </div>
        </div>

        {/* Step indicator dots */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 6, marginBottom: 22 }}>
          {(['email', 'otp', 'newpass', 'done'] as ForgotStep[]).map((s, i) => {
            const steps: ForgotStep[] = ['email', 'otp', 'newpass', 'done']
            const current = steps.indexOf(step)
            const isDone = i < current
            const isActive = s === step
            return (
              <div key={s} style={{
                width: isActive ? 20 : 7, height: 7,
                borderRadius: 4,
                background: isActive ? 'var(--accent)' : isDone ? 'var(--success)' : 'var(--border)',
                transition: 'all 0.25s ease',
              }} />
            )
          })}
        </div>

        {/* ── Step: Enter email ── */}
        {step === 'email' && (
          <form onSubmit={handleSendOtp} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label className="form-label">Email address</label>
              <input
                id="forgot-email"
                className="auth-input"
                type="email"
                placeholder="you@company.com"
                value={email}
                onChange={e => { setEmail(e.target.value); setError(null) }}
                autoComplete="email"
                autoFocus
              />
            </div>

            {error && (
              <div className="auth-error" style={{ margin: 0 }}>
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}

            <button
              id="forgot-send-btn"
              className="btn btn-primary auth-submit"
              type="submit"
              disabled={busy}
              style={{ marginTop: 0 }}
            >
              {busy ? <><Loader2 size={14} className="notif-spin" style={{ marginRight: 6 }} />Sending…</> : 'Send reset code'}
            </button>
          </form>
        )}

        {/* ── Step: Enter OTP ── */}
        {step === 'otp' && (
          <form onSubmit={handleVerifyOtp} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label className="form-label">6-digit code</label>
              <input
                id="forgot-otp"
                className="auth-input"
                type="text"
                inputMode="numeric"
                maxLength={6}
                placeholder="123456"
                value={otp}
                onChange={e => { setOtp(e.target.value.replace(/\D/g, '')); setError(null) }}
                autoFocus
                style={{ letterSpacing: '0.35em', fontSize: 18, textAlign: 'center' }}
              />
            </div>

            <p style={{ margin: 0, fontSize: 11, color: 'var(--text-dim)', textAlign: 'center' }}>
              Didn't get the email?{' '}
              <button
                type="button"
                style={{ color: 'var(--accent)', fontWeight: 600, fontSize: 11, padding: '0 2px' }}
                onClick={() => { setStep('email'); setOtp(''); setError(null) }}
              >
                Resend
              </button>
            </p>

            {error && (
              <div className="auth-error" style={{ margin: 0 }}>
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}

            <button
              id="forgot-verify-btn"
              className="btn btn-primary auth-submit"
              type="submit"
              disabled={busy || otp.length !== 6}
              style={{ marginTop: 0 }}
            >
              Verify code
            </button>
          </form>
        )}

        {/* ── Step: New password ── */}
        {step === 'newpass' && (
          <form onSubmit={handleResetPassword} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label className="form-label">New password</label>
              <div style={{ position: 'relative' }}>
                <PasswordInput
                  value={newPass}
                  onChange={v => { setNewPass(v); setError(null); newPassCheck.reset() }}
                  placeholder="••••••••"
                  visible={showNewPass}
                  onToggleVisible={() => setShowNewPass(v => !v)}
                  onBlur={() => newPassCheck.run(newPass)}
                />
                <FieldStatus check={newPassCheck.check} okTitle="Password is new and strong." />
              </div>
              {newPassCheck.check.state === 'bad' && (
                <div className="auth-error" style={{ margin: '4px 0 0', padding: '8px 12px' }}>
                  <AlertCircle size={15} style={{ flexShrink: 0 }} />
                  <span>{newPassCheck.check.message}</span>
                </div>
              )}
            </div>

            <div className="auth-field" style={{ marginBottom: 0 }}>
              <label className="form-label">Confirm password</label>
              <PasswordInput
                value={confirmPass}
                onChange={v => { setConfirmPass(v); setError(null) }}
                placeholder="••••••••"
                visible={showConfirmPass}
                onToggleVisible={() => setShowConfirmPass(v => !v)}
              />
            </div>

            {error && (
              <div className="auth-error" style={{ margin: 0 }}>
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}

            <button
              id="forgot-reset-btn"
              className="btn btn-primary auth-submit"
              type="submit"
              disabled={busy || newPassCheck.check.state === 'checking' || newPassCheck.check.state === 'bad'}
              style={{ marginTop: 0 }}
            >
              {busy ? <><Loader2 size={14} className="notif-spin" style={{ marginRight: 6 }} />Updating…</> : 'Update password'}
            </button>
          </form>
        )}

        {/* ── Step: Done ── */}
        {step === 'done' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <button
              id="forgot-done-btn"
              className="btn btn-primary auth-submit"
              onClick={dismiss}
              style={{ marginTop: 0 }}
            >
              Back to sign in
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

// ── Main Auth Screen ───────────────────────────────────────────────────────────

export default function AuthScreen() {
  const { login } = useAuth()
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [signupStep, setSignupStep] = useState<'details' | 'otp' | 'password'>('details')
  const [signupOtp, setSignupOtp] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [identifier, setIdentifier] = useState('')   // login: username OR email
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [showForgot, setShowForgot] = useState(false)

  const isSignup = mode === 'signup'

  // Username availability and email deliverability, both checked on blur.
  const nameCheck = useFieldCheck(u => usernameProblem(u) === null, apiCheckUsername)
  const emailCheck = useFieldCheck(emailOk, apiCheckEmail)

  // Client-side gate — keep the submit button honest before hitting the backend.
  function localError(): string | null {
    if (isSignup) {
      if (signupStep === 'details') {
        const uErr = usernameProblem(username)
        if (uErr) return `Username must be ${uErr}.`
        if (nameCheck.check.state === 'bad') return nameCheck.check.message
        if (!emailOk(email)) return 'Enter a valid email address.'
        if (emailCheck.check.state === 'bad') return emailCheck.check.message
      } else if (signupStep === 'otp') {
        if (signupOtp.length !== 6) return 'Verification code must be 6 digits.'
      } else if (signupStep === 'password') {
        const pw = passwordProblem(password)
        if (pw) return `Password needs ${pw}.`
        if (password !== confirm) return 'Passwords do not match.'
      }
    } else {
      if (!identifier.trim()) return 'Username or email is required.'
      if (!password) return 'Password is required.'
    }
    return null
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const problem = localError()
    if (problem) { setError(problem); return }
    setBusy(true)
    try {
      if (isSignup) {
        if (signupStep === 'details') {
          await apiSignupRequest(username.trim(), email.trim())
          setSignupStep('otp')
        } else if (signupStep === 'otp') {
          await apiSignupVerifyOtp(email.trim(), signupOtp.trim())
          setSignupStep('password')
        } else if (signupStep === 'password') {
          const user = await apiSignupFinalize(email.trim(), signupOtp.trim(), password)
          login(user)
        }
      }
      else {
        const user = await apiLogin(identifier, password)
        login(user)
      }
      // success → AuthProvider sets user, App swaps to the real UI. Nothing else.
    } catch (err) {
      // Tauri invoke rejects with the Rust Err(String); fall back for anything else.
      setError(typeof err === 'string' ? err
             : err instanceof Error ? err.message
             : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  function switchMode() {
    setMode(isSignup ? 'login' : 'signup')
    setSignupStep('details')
    setSignupOtp('')
    setError(null)
    setConfirm('')
    nameCheck.reset()
    emailCheck.reset()
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={onSubmit}>
        <div className="auth-brand">
          <img src="/logo.png" alt="ENSTUDIO" />
          <span className="logo-text">ENSTUDIO</span>
        </div>
        <p className="auth-subtitle">
          {isSignup && signupStep === 'otp' ? 'Check your email for the code' :
           isSignup && signupStep === 'password' ? 'Set a password for your account' :
           isSignup ? 'Create your account to get started' : 'Sign in to continue'}
        </p>

        {isSignup && signupStep === 'otp' ? (
          <>
            <div className="auth-field">
              <label className="form-label">Verification Code</label>
              <input
                className="auth-input"
                placeholder="123456"
                value={signupOtp}
                onChange={e => {
                  setSignupOtp(e.target.value)
                  setError(null)
                }}
                autoFocus
                maxLength={6}
                style={{ fontSize: 24, letterSpacing: 8, textAlign: 'center', padding: '12px 0' }}
              />
            </div>
            {error && (
              <div className="auth-error">
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}
            <button className="btn btn-primary auth-submit" type="submit" disabled={busy}>
              {busy ? 'Verifying…' : 'Validate Code'}
            </button>
            <div className="auth-switch">
              <button type="button" onClick={() => setSignupStep('details')}>
                Back
              </button>
            </div>
          </>
        ) : isSignup && signupStep === 'password' ? (
          <>
            <div className="auth-field">
              <label className="form-label">Password</label>
              <PasswordInput
                value={password}
                onChange={setPassword}
                placeholder="••••••••"
                visible={showPassword}
                onToggleVisible={() => setShowPassword(v => !v)}
              />
            </div>
            <div className="auth-field">
              <label className="form-label">Confirm password</label>
              <PasswordInput
                value={confirm}
                onChange={setConfirm}
                placeholder="••••••••"
                visible={showConfirm}
                onToggleVisible={() => setShowConfirm(v => !v)}
              />
            </div>
            {error && (
              <div className="auth-error">
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}
            <button className="btn btn-primary auth-submit" type="submit" disabled={busy}>
              {busy ? 'Creating account…' : 'Create account'}
            </button>
            <div className="auth-switch">
              <button type="button" onClick={() => setSignupStep('otp')}>
                Back
              </button>
            </div>
          </>
        ) : (
          <>
            {isSignup ? (
              <>
                <div className="auth-field">
                  <label className="form-label">Username</label>
                  <div className="auth-input-wrap">
                    <input className="auth-input" placeholder="jane.doe" value={username}
                           onChange={e => {
                             setUsername(e.target.value)
                             nameCheck.reset()
                           }}
                           onBlur={() => nameCheck.run(username)}
                           autoComplete="username" />
                    <FieldStatus check={nameCheck.check} okTitle="Username is available" />
                  </div>
                  {nameCheck.check.state === 'bad' && (
                    <span className="auth-hint auth-hint--bad">{nameCheck.check.message}</span>
                  )}
                </div>
                <div className="auth-field">
                  <label className="form-label">Email</label>
                  <div className="auth-input-wrap">
                    <input className="auth-input" type="email" placeholder="you@company.com" value={email}
                           onChange={e => {
                             setEmail(e.target.value)
                             emailCheck.reset()
                           }}
                           onBlur={() => emailCheck.run(email)}
                           autoComplete="email" />
                    <FieldStatus check={emailCheck.check} okTitle="Domain accepts email" />
                  </div>
                  {emailCheck.check.state === 'bad' && (
                    <span className="auth-hint auth-hint--bad">{emailCheck.check.message}</span>
                  )}
                </div>
                
                {error && (
                  <div className="auth-error">
                    <AlertCircle size={15} style={{ flexShrink: 0 }} />
                    <span>{error}</span>
                  </div>
                )}
                
                <button className="btn btn-primary auth-submit" type="submit" disabled={busy}>
                  {busy ? 'Please wait…' : 'Verify email'}
                </button>
              </>
            ) : (
              <>
                <div className="auth-field">
                  <label className="form-label">Username or email</label>
                  <input className="auth-input" placeholder="jane.doe or you@company.com" value={identifier}
                         onChange={e => setIdentifier(e.target.value)} autoComplete="username" />
                </div>
                <div className="auth-field">
                  <label className="form-label">Password</label>
                  <PasswordInput
                    value={password}
                    onChange={setPassword}
                    placeholder="••••••••"
                    visible={showPassword}
                    onToggleVisible={() => setShowPassword(v => !v)}
                  />
                  <button
                    type="button"
                    id="forgot-password-btn"
                    className="auth-link"
                    style={{ alignSelf: 'flex-start' }}
                    onClick={() => setShowForgot(true)}
                  >
                    Forgot password?
                  </button>
                </div>
                
                {error && (
                  <div className="auth-error">
                    <AlertCircle size={15} style={{ flexShrink: 0 }} />
                    <span>{error}</span>
                  </div>
                )}

                <button className="btn btn-primary auth-submit" type="submit" disabled={busy}>
                  {busy ? 'Please wait…' : 'Sign in'}
                </button>
              </>
            )}

            <div className="auth-switch">
              {isSignup ? 'Already have an account? ' : "Don't have an account? "}
              <button type="button" onClick={switchMode}>
                {isSignup ? 'Sign in' : 'Signup'}
              </button>
            </div>
          </>
        )}
      </form>

      {/* Forgot Password modal — portaled to document.body */}
      {showForgot && <ForgotPasswordModal onClose={() => setShowForgot(false)} />}
    </div>
  )
}

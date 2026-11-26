import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { toast } from 'sonner'
import { X, User, Save } from 'lucide-react'
import { useAuth } from '../state/useAuth'

/** Edit the logged-in user's name/email — backed by the real update_user
 * command (name/email required, email format + uniqueness validated server-side). */
export function EditProfileModal({ onClose }: { onClose: () => void }) {
  const { user, updateProfile } = useAuth()
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const dismiss = () => { setOpen(false); setTimeout(onClose, 160) }

  const [name, setName] = useState(user?.name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [saving, setSaving] = useState(false)

  if (!user) return null

  async function handleSave() {
    if (!user) return
    if (!name.trim() || !email.trim()) {
      toast.error('Name and email cannot be empty')
      return
    }
    setSaving(true)
    try {
      await updateProfile(user.id, name.trim(), email.trim())
      toast.success('Profile updated')
      dismiss()
    } catch (e: unknown) {
      toast.error(typeof e === 'string' ? e : 'Failed to update profile')
    } finally {
      setSaving(false)
    }
  }

  return createPortal(
    <div
      className={`modal-backdrop${open ? ' open' : ''}`}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
      }}
      onClick={e => { if (e.target === e.currentTarget) dismiss() }}
    >
      <div className="modal-dialog" style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '22px 22px 20px', width: 420,
        display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
            <User size={18} className="text-accent" /> Edit Profile
          </div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Name</span>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Your name"
            style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px', color: 'var(--text-primary)', outline: 'none' }}
            onFocus={e => e.target.style.borderColor = 'var(--accent)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Email</span>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com"
            style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px', color: 'var(--text-primary)', outline: 'none' }}
            onFocus={e => e.target.style.borderColor = 'var(--accent)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="btn btn-ghost" onClick={dismiss}>Cancel</button>
          <button className="btn btn-primary" disabled={saving} onClick={handleSave} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Save size={14} /> {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

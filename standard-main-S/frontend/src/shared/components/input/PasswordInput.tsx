import { Eye, EyeOff } from 'lucide-react'

// Password field with a show/hide toggle — was duplicated identically for
// the Anthropic and Gemini key inputs in UsageScreen.
export function PasswordInput({
  value, onChange, placeholder, visible, onToggleVisible, className, onBlur
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  visible: boolean
  onToggleVisible: () => void
  className?: string
  onBlur?: () => void
}) {
  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
      <input
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className={className}
        style={{ width: '100%', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 40px 10px 14px', color: 'var(--text-primary)', outline: 'none' }}
        onFocus={e => e.target.style.borderColor = 'var(--accent)'}
        onBlur={e => {
          e.target.style.borderColor = 'var(--border)'
          if (onBlur) onBlur()
        }}
      />
      <button
        type="button"
        onClick={onToggleVisible}
        style={{ position: 'absolute', right: 12, background: 'none', border: 'none', color: 'white', cursor: 'pointer', display: 'flex', padding: 0 }}
      >
        {visible ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  )
}

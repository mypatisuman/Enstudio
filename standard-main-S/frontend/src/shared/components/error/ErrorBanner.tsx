import { XCircle } from 'lucide-react'

// Byte-identical error banner previously duplicated in GapsScreen, HomeScreen,
// and ReviewScreen (only the padding value differed between Home and the
// other two — kept as a prop rather than forced to one value).
export function ErrorBanner({ message, padding = '16px 20px' }: { message: string; padding?: string }) {
  return (
    <div style={{
      padding, background: 'rgba(239,68,68,0.08)',
      border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--r-md)',
      color: 'var(--danger)', fontSize: 13, display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <XCircle size={16} strokeWidth={2} />
      {message}
    </div>
  )
}

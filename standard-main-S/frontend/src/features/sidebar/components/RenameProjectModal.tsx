import ConfirmModal from '../../../components/ConfirmModal'
import { TextInput } from '../../../shared/components/input/TextInput'

export function RenameProjectModal({
  renameInput, setRenameInput, renameBusy, onConfirm, onCancel,
}: {
  renameInput: string
  setRenameInput: (v: string) => void
  renameBusy: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <ConfirmModal
      title="Rename Project"
      confirmLabel={renameBusy ? 'Saving...' : 'Save'}
      confirmDisabled={renameBusy || !renameInput.trim()}
      onConfirm={onConfirm}
      onCancel={onCancel}
      body={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Project name
          </label>
          <TextInput
            type="text"
            value={renameInput}
            onChange={e => setRenameInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onConfirm(); if (e.key === 'Escape') onCancel() }}
            autoFocus
            focusAccent
          />
        </div>
      }
    />
  )
}

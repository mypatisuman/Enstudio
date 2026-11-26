import type { RefObject } from 'react'
import ConfirmModal from '../../../components/ConfirmModal'
import { TextInput } from '../../../shared/components/input/TextInput'

export function NewProjectModal({
  newName, setNewName, createErr, setCreateErr, creating, nameInputRef,
  onCreate, onCancel,
}: {
  newName: string
  setNewName: (v: string) => void
  createErr: string
  setCreateErr: (v: string) => void
  creating: boolean
  nameInputRef: RefObject<HTMLInputElement | null>
  onCreate: () => void
  onCancel: () => void
}) {
  return (
    <ConfirmModal
      title="New project"
      width={360}
      confirmLabel={creating ? 'Creating…' : 'Create →'}
      confirmDisabled={!newName.trim() || creating}
      onConfirm={onCreate}
      onCancel={onCancel}
      body={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Project name
          </label>
          <TextInput
            ref={nameInputRef}
            type="text"
            placeholder="e.g. Ethylene Reactor Section"
            value={newName}
            onChange={e => { setNewName(e.target.value); setCreateErr('') }}
            onKeyDown={e => { if (e.key === 'Enter') onCreate(); if (e.key === 'Escape') onCancel() }}
            focusAccent
          />
          {createErr && (
            <div style={{ fontSize: 11, color: 'var(--danger)', marginTop: 2 }}>{createErr}</div>
          )}
        </div>
      }
    />
  )
}

import ConfirmModal from '../../../components/ConfirmModal'
import type { Project } from '../../../App'

export function DeleteProjectModal({
  project, onConfirm, onCancel,
}: {
  project: Project
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <ConfirmModal
      title="Delete project"
      titleColor="var(--danger)"
      confirmLabel="Delete"
      confirmDanger
      onConfirm={onConfirm}
      onCancel={onCancel}
      body={
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Are you sure you want to delete <strong>"{project.name || project.id}"</strong>?<br/>
          This will permanently delete all associated drawings and extracted data.
        </div>
      }
    />
  )
}

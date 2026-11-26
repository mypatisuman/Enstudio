import type { Project } from '../../../App'
import { Pill } from './Pill'

export function ProjectHeader({
  project, nodeCount, edgeCount, lastExtracted,
}: {
  project: Project
  nodeCount: number
  edgeCount: number
  lastExtracted: string
}) {
  return (
    <div>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: 'var(--text-primary)', marginBottom: 4 }}>
        {project.name || project.id}
      </h1>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
        <Pill label="drawings" value={project.drawings} />
        <Pill label="instruments" value={project.instruments} />
        <Pill label="equipment" value={project.equipment} />
        <Pill label="nodes" value={nodeCount} />
        <Pill label="edges" value={edgeCount} />
        {lastExtracted && <Pill label="last extracted" value={lastExtracted} />}
      </div>
    </div>
  )
}

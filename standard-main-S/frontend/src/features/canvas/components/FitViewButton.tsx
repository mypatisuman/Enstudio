import { useReactFlow } from '@xyflow/react'

export function FitViewButton() {
  const { fitView } = useReactFlow()
  return (
    <button className="btn btn-ghost" style={{ fontSize: 11, padding: '3px 8px' }}
      onClick={() => fitView({ padding: 0.2 })}>⊡ Fit</button>
  )
}

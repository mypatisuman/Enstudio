// Rendered as a React Flow node (id "__pidbg__") so the drawing pans/zooms in the
// SAME transform as the symbol nodes — a fixed <img> sibling would not line up.
export function PidBgNode({ data }: { data: { url: string; w: number; h: number } }) {
  return (
    <img
      src={data.url}
      alt=""
      draggable={false}
      style={{
        width: data.w, height: data.h, opacity: 0.8,
        pointerEvents: 'none', display: 'block'
      }}
    />
  )
}

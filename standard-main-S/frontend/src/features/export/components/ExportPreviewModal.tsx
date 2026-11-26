import { useRef } from 'react'
import type { Dispatch, SetStateAction } from 'react'

export interface ViewFile { name: string; content: string }

export function ExportPreviewModal({
  viewFile, setViewFile, svgZoom, setSvgZoom,
}: {
  viewFile: ViewFile
  setViewFile: (v: ViewFile | null) => void
  svgZoom: number
  setSvgZoom: Dispatch<SetStateAction<number>>
}) {
  const svgPanRef       = useRef<{ startX: number; startY: number; scrollLeft: number; scrollTop: number } | null>(null)
  const svgContainerRef = useRef<HTMLDivElement>(null)

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(15,23,42,0.85)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
      padding: 40,
    }}>
      <div style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 12, width: '100%', maxWidth: 1000, height: '100%', maxHeight: 800,
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 25px 50px -12px rgba(0,0,0,0.15)',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 24px', borderBottom: '1px solid var(--border)',
          background: 'var(--bg-primary)', borderRadius: '12px 12px 0 0',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 18 }}>📄</span>
            <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 16 }}>{viewFile.name}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {viewFile.name.endsWith('.svg') && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button className="btn btn-ghost" style={{ fontSize: 18, padding: '2px 10px' }} onClick={() => setSvgZoom(z => Math.max(0.1, z - 0.05))}>−</button>
                <span style={{ fontSize: 12, color: 'var(--text-muted)', minWidth: 44, textAlign: 'center' }}>{Math.round(svgZoom * 100)}%</span>
                <button className="btn btn-ghost" style={{ fontSize: 18, padding: '2px 10px' }} onClick={() => setSvgZoom(z => Math.min(2, z + 0.05))}>+</button>
                <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => setSvgZoom(1)}>Reset</button>
              </div>
            )}
            <button className="btn btn-ghost" onClick={() => { setViewFile(null); setSvgZoom(1) }} style={{ fontSize: 18, padding: '4px 8px' }}>✕</button>
          </div>
        </div>
        <div style={{ flex: 1, overflow: 'hidden', background: 'var(--bg-secondary)', display: 'flex', flexDirection: 'column' }}>
          {viewFile.name.endsWith('.svg') ? (
            <>
              <div
                ref={svgContainerRef}
                style={{ flex: 1, overflow: 'auto', cursor: 'grab', background: '#f8fafc', padding: 20 }}
                onMouseDown={e => {
                  const el = svgContainerRef.current; if (!el) return
                  svgPanRef.current = { startX: e.clientX, startY: e.clientY, scrollLeft: el.scrollLeft, scrollTop: el.scrollTop }
                  el.style.cursor = 'grabbing'
                }}
                onMouseMove={e => {
                  if (!svgPanRef.current || !svgContainerRef.current) return
                  const dx = e.clientX - svgPanRef.current.startX
                  const dy = e.clientY - svgPanRef.current.startY
                  svgContainerRef.current.scrollLeft = svgPanRef.current.scrollLeft - dx
                  svgContainerRef.current.scrollTop  = svgPanRef.current.scrollTop  - dy
                }}
                onMouseUp={() => { svgPanRef.current = null; if (svgContainerRef.current) svgContainerRef.current.style.cursor = 'grab' }}
                onMouseLeave={() => { svgPanRef.current = null; if (svgContainerRef.current) svgContainerRef.current.style.cursor = 'grab' }}
                onWheel={e => { e.preventDefault(); setSvgZoom(z => Math.min(2, Math.max(0.1, z - e.deltaY * 0.001))) }}
              >
                <div
                  className="svg-preview-wrapper"
                  dangerouslySetInnerHTML={{ __html: viewFile.content }}
                  style={{
                    width: `${svgZoom * 100}%`,
                    height: `${svgZoom * 100}%`,
                    minWidth: `${svgZoom * 100}%`,
                    minHeight: `${svgZoom * 100}%`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    userSelect: 'none'
                  }}
                />
              </div>
            </>
          ) : (
            <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
              <pre style={{ margin: 0, fontFamily: 'monospace', fontSize: 13, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {viewFile.content}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

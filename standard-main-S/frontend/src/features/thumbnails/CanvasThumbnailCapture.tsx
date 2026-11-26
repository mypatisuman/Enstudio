import { useEffect, useRef } from 'react'
import { toPng } from 'html-to-image'
import CanvasScreen from '../../components/screens/CanvasScreen'
import type { Project } from '../../App'

const CAPTURE_W = 480
const CAPTURE_H = 300
// How long to wait, after nodes first appear in the DOM, for CanvasScreen's
// own fitView (fired ~100ms after layout) to settle before we screenshot —
// and the hard ceiling if a project's graph never renders anything (empty
// project — a legitimate case, not a bug) so we don't hang the queue forever.
const SETTLE_MS = 450
const MAX_WAIT_MS = 6000
const POLL_MS = 120

/**
 * Mounts the real CanvasScreen off-screen for one project, waits for its
 * own async load+layout to settle, captures a PNG of the rendered canvas via
 * html-to-image, then reports the result. The caller owns unmounting this
 * once onDone fires — kept to one at a time by the caller's queue so we
 * never have more than one full interactive Canvas instance alive for this
 * purely-thumbnail purpose.
 */
export function CanvasThumbnailCapture({ project, onDone }: {
  project: Project
  onDone: (dataUrl: string | null) => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const doneRef = useRef(false)

  useEffect(() => {
    doneRef.current = false
    const start = Date.now()
    let settleTimer: ReturnType<typeof setTimeout> | null = null

    const finish = async () => {
      if (doneRef.current) return
      doneRef.current = true
      const flowEl = wrapRef.current?.querySelector('.react-flow') as HTMLElement | null
      if (!flowEl) {
        console.error('[thumbnail] no .react-flow element found for', project.id)
        onDone(null)
        return
      }
      try {
        // No backgroundColor override — the real element already carries
        // CanvasScreen's own Theme.canvas background inline; capture it as-is.
        const dataUrl = await toPng(flowEl, {
          width: CAPTURE_W,
          height: CAPTURE_H,
          pixelRatio: 1,
        })
        onDone(dataUrl)
      } catch (err) {
        console.error('[thumbnail] capture failed for', project.id, err)
        onDone(null)
      }
    }

    const poll = setInterval(() => {
      if (doneRef.current) { clearInterval(poll); return }
      const hasNodes = !!wrapRef.current?.querySelector('.react-flow__node')
      const timedOut = Date.now() - start > MAX_WAIT_MS
      if (hasNodes && !settleTimer) {
        // Give CanvasScreen's own fitView (setTimeout 100ms) time to run and paint.
        settleTimer = setTimeout(finish, SETTLE_MS)
      } else if (timedOut) {
        console.error('[thumbnail] timed out waiting for nodes to render for', project.id)
        clearInterval(poll)
        finish()
      }
    }, POLL_MS)

    return () => {
      clearInterval(poll)
      if (settleTimer) clearTimeout(settleTimer)
    }
  }, [project.id, onDone])

  return (
    <div
      ref={wrapRef}
      aria-hidden="true"
      style={{
        // In-viewport but invisible — avoids relying on WebView2 to fully
        // paint/layout content positioned far outside the visible area,
        // which some Chromium-based webviews are inconsistent about.
        position: 'fixed', top: 0, left: 0, zIndex: -1,
        width: CAPTURE_W, height: CAPTURE_H,
        overflow: 'hidden', opacity: 0.01, pointerEvents: 'none',
      }}
    >
      {/* Scoped to this capture instance only — hides interactive chrome
          (minimap/controls/attribution) that doesn't belong in a thumbnail. */}
      <style>{`
        .react-flow__minimap, .react-flow__controls, .react-flow__attribution { display: none !important; }
      `}</style>
      <CanvasScreen project={project} />
    </div>
  )
}

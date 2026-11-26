import { useState, useEffect, useCallback } from 'react'
import { CanvasThumbnailCapture } from './CanvasThumbnailCapture'
import { getCachedThumb, setCachedThumb, hasFailed, markFailed } from './thumbnailCache'
import type { Project } from '../../App'

/**
 * Real Canvas-screen thumbnails for a list of projects — captured off-screen
 * from the actual CanvasScreen component, one project at a time (bounded
 * concurrency, never more than one heavy Canvas instance mounted at once).
 * Cached by pid+last_extraction, so a re-extraction refreshes the thumbnail
 * instead of showing a stale one.
 *
 * Returns the resolved thumbnails plus a node the caller must render
 * somewhere in its tree (it does the actual off-screen mounting/capturing).
 */
export function useCanvasThumbnails(projects: Project[]) {
  const [thumbs, setThumbs] = useState<Record<string, string>>({})
  const [queue, setQueue] = useState<Project[]>([])

  useEffect(() => {
    const fromCache: Record<string, string> = {}
    const toQueue: Project[] = []
    projects.forEach(p => {
      if (thumbs[p.id]) return
      if (hasFailed(p.id)) return
      const cached = getCachedThumb(p.id, p.last_extraction)
      if (cached != null) fromCache[p.id] = cached
      else toQueue.push(p)
    })
    if (Object.keys(fromCache).length) setThumbs(prev => ({ ...prev, ...fromCache }))
    if (toQueue.length) {
      setQueue(prev => {
        const existingIds = new Set(prev.map(p => p.id))
        return [...prev, ...toQueue.filter(p => !existingIds.has(p.id))]
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.map(p => `${p.id}:${p.last_extraction}`).join(',')])

  const capturing = queue[0]
  // Stable per-project identity — CanvasThumbnailCapture's polling effect
  // depends on this, so it must not change on unrelated re-renders (only
  // when the queue actually advances to a different project).
  const handleDone = useCallback((dataUrl: string | null) => {
    setQueue(prev => {
      const [current, ...rest] = prev
      if (current) {
        if (dataUrl) {
          setCachedThumb(current.id, current.last_extraction, dataUrl)
          setThumbs(t => ({ ...t, [current.id]: dataUrl }))
        } else {
          markFailed(current.id)
        }
      }
      return rest
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capturing?.id])

  const captureNode = capturing
    ? <CanvasThumbnailCapture project={capturing} onDone={handleDone} />
    : null

  return { thumbs, captureNode }
}

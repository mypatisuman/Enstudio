import { useEffect, useState } from 'react'

/**
 * Keeps a component mounted through its exit animation so open AND close both
 * animate. Render while `mounted`; drive the enter/exit CSS class off `open`
 * (a class like `.foo` closed + `.foo.open` open, transitioned).
 *
 * exitMs must match the CSS transition duration, or the element is yanked early.
 */
export function useMountTransition(isOpen: boolean, exitMs = 180) {
  const [mounted, setMounted] = useState(isOpen)
  const [open, setOpen] = useState(isOpen)

  // setMounted/setOpen below run synchronously in the effect body (flagged
  // by react-hooks/set-state-in-effect) — deliberately not deferred further:
  // `mounted` gates whether the DOM node exists at all, so pushing this call
  // into a microtask/rAF would delay mounting by a frame and risk a visible
  // flash of missing content on open. Same reasoning applies to every other
  // "load on mount"/"reset on dependency change" effect across the app
  // (see ExportScreen's data-load effect for the broader pattern) — this is
  // the standard, consistently-used shape, not an oversight.
  useEffect(() => {
    if (isOpen) {
      setMounted(true)
      // next frame, so the enter transition runs from the closed state
      const r = requestAnimationFrame(() => setOpen(true))
      return () => cancelAnimationFrame(r)
    }
    setOpen(false)
    const t = setTimeout(() => setMounted(false), exitMs)
    return () => clearTimeout(t)
  }, [isOpen, exitMs])

  return { mounted, open }
}

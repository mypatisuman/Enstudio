// Tiny cross-screen bridge so the Review table can ask the Canvas to locate a
// node by tag WITHOUT duplicating navigation logic. Review sets a pending tag
// + navigates to Canvas; CanvasFlow consumes it once its graph is loaded and
// reuses its existing focusNode (highlight + animated zoom). Additive — does
// not change any existing canvas behavior.

let pendingTag: string | null = null

export function requestCanvasFocus(tag: string) {
  pendingTag = tag
  // Fire for the already-mounted case; the mount-time consumer covers the
  // navigate-then-mount case (event fired before the listener existed).
  window.dispatchEvent(new Event('enstudio:canvas-focus'))
}

/** Returns and clears the pending focus tag (once). */
export function takePendingFocus(): string | null {
  const t = pendingTag
  pendingTag = null
  return t
}

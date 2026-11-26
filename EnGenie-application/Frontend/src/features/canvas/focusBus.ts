// Cross-component focus bus to center and highlight nodes on the P&ID canvas

let pendingTag: string | null = null;

export function requestCanvasFocus(tag: string) {
  pendingTag = tag;
  window.dispatchEvent(new Event('engenie:canvas-focus'));
}

/** Returns and clears the pending focus tag (once). */
export function takePendingFocus(): string | null {
  const t = pendingTag;
  pendingTag = null;
  return t;
}

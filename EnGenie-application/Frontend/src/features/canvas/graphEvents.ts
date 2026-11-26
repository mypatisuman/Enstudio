// Event bus for notifying canvas components when graph data is updated externally (e.g. by Describe Agents)

export function emitGraphChanged(projectId: string = 'default') {
  window.dispatchEvent(new CustomEvent('engenie:graph-changed', { detail: { projectId } }));
}

export function onGraphChanged(callback: (projectId: string) => void): () => void {
  const handler = (e: Event) => {
    const detail = (e as CustomEvent).detail;
    callback(detail?.projectId || 'default');
  };
  window.addEventListener('engenie:graph-changed', handler);
  return () => window.removeEventListener('engenie:graph-changed', handler);
}

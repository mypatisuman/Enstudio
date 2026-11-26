import type { GraphData, GraphNode, GraphEdge } from '../features/canvas/types';

const BASE_URL = '';

/** Helper to retrieve the current active PID graph from local cache or API */
export async function getGraph(sessionId: string): Promise<GraphData> {
  if (!sessionId) {
    const cached = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
    if (cached) {
      try { return JSON.parse(cached); } catch {}
    }
    return { nodes: [], edges: [] };
  }

  try {
    const token = localStorage.getItem('auth_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`/api/pid/active?session_id=${encodeURIComponent(sessionId)}`, {
      headers,
      credentials: 'include',
    });
    if (res.ok) {
      const data = await res.json();
      if (data.pid_graph) {
        // Cache to storage
        sessionStorage.setItem('active_pid_graph', JSON.stringify(data.pid_graph));
        localStorage.setItem('active_pid_graph', JSON.stringify(data.pid_graph));
        return data.pid_graph;
      }
    }
  } catch (e) {
    console.warn('[pidGraphService] Failed to load remote graph, falling back to cache:', e);
  }

  const cached = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
  if (cached) {
    try { return JSON.parse(cached); } catch {}
  }

  return { nodes: [], edges: [] };
}

/** Mutate local cached graph and trigger storage update */
function updateCachedGraph(updater: (g: GraphData) => void): GraphData {
  let g: GraphData = { nodes: [], edges: [] };
  try {
    const raw = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
    if (raw) g = JSON.parse(raw);
  } catch {}

  updater(g);

  const json = JSON.stringify(g);
  localStorage.setItem('active_pid_graph', json);
  sessionStorage.setItem('active_pid_graph', json);
  window.dispatchEvent(new CustomEvent('engenie:graph-changed', { detail: g }));
  return g;
}

export async function insertEdgeById(sessionId: string, fromId: string, toId: string, kind = 'stream'): Promise<void> {
  updateCachedGraph(g => {
    if (!g.edges) g.edges = [];
    const exists = g.edges.some(e => e.source === fromId && e.target === toId);
    if (!exists) {
      g.edges.push({ source: fromId, target: toId, kind });
    }
  });
}

export async function deleteEdgeById(sessionId: string, fromId: string, toId: string): Promise<void> {
  updateCachedGraph(g => {
    if (g.edges) {
      g.edges = g.edges.filter(e => !(e.source === fromId && e.target === toId));
    }
  });
}

export async function deleteNode(sessionId: string, nodeId: string): Promise<void> {
  updateCachedGraph(g => {
    if (g.nodes) {
      g.nodes = g.nodes.filter(n => n.id !== nodeId && n.label !== nodeId);
    }
    if (g.edges) {
      g.edges = g.edges.filter(e => e.source !== nodeId && e.target !== nodeId);
    }
  });
}

export async function updateNode(
  sessionId: string, nodeId: string, label: string, kind: string, area: string, description: string,
): Promise<void> {
  updateCachedGraph(g => {
    const node = g.nodes?.find(n => n.id === nodeId || n.label === nodeId);
    if (node) {
      node.label = label;
      node.kind = kind;
      node.area = area;
      if (description) (node as any).description = description;
    }
  });
}

export async function updateNodePosition(sessionId: string, nodeId: string, x: number, y: number): Promise<void> {
  updateCachedGraph(g => {
    const node = g.nodes?.find(n => n.id === nodeId || n.label === nodeId);
    if (node) {
      node.x = Math.round(x);
      node.y = Math.round(y);
    }
  });
}

export async function updateEdgeBend(sessionId: string, fromId: string, toId: string, x: number, y: number): Promise<void> {
  updateCachedGraph(g => {
    const edge = g.edges?.find(e => e.source === fromId && e.target === toId);
    if (edge) {
      edge.bend_x = x;
      edge.bend_y = y;
    }
  });
}

export async function clearEdgeBend(sessionId: string, fromId: string, toId: string): Promise<void> {
  updateCachedGraph(g => {
    const edge = g.edges?.find(e => e.source === fromId && e.target === toId);
    if (edge) {
      delete edge.bend_x;
      delete edge.bend_y;
    }
  });
}

export async function batchInsertNodes(sessionId: string, nodesJson: string): Promise<{ ids: Array<{ id: string }> }> {
  try {
    const parsed: Array<{ tag: string; kind: string; area?: string; description?: string }> = JSON.parse(nodesJson);
    const addedIds: Array<{ id: string }> = [];

    updateCachedGraph(g => {
      if (!g.nodes) g.nodes = [];
      for (const item of parsed) {
        const id = item.tag || `node_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
        g.nodes.push({
          id,
          label: item.tag,
          kind: item.kind,
          area: item.area || '',
          x: 400 + Math.random() * 200,
          y: 300 + Math.random() * 200,
        });
        addedIds.push({ id });
      }
    });

    return { ids: addedIds };
  } catch (e) {
    console.error('[pidGraphService] Failed batch insert nodes:', e);
    return { ids: [] };
  }
}

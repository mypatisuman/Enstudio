export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  area: string;
  drawing: string;
  x: number;
  y: number;
}
export interface GraphEdge { source: string; target: string; kind: string }
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[] }

export interface ChatEntry {
  id?: string;
  dbId?: string;
  role: 'user' | 'assistant';
  display: string;
  apiContent?: string;
  agent?: string;
  reasoning?: string;
  nodesAdded?: number;
  edgesAdded?: number;
  nodesUpdated?: number;
  nodesDeleted?: number;
  isError?: boolean;
  pendingDeletes?: string[];
  deleteResolution?: 'confirmed' | 'cancelled';
  ops?: any[];
  solution_design?: any;
  timestamp?: string;
  answerMarkdown?: boolean;
  results?: { tag: string; title: string; detail: string }[];
  /** build | update | question | mixed | chat */
  mode?: string;
  sources?: string[];
  attachments?: { name: string; kind: string }[];
}

export interface DescribeSession {
  id: string;
  title: string;
  updated_at?: string;
  created_at?: string;
  message_count?: number;
  pinned?: boolean;
  project?: string;
  archived?: boolean;
}

export interface PendingAttachment {
  id: string;
  name: string;
  kind: 'image' | 'pdf' | 'text' | 'docx';
  mime: string;
  base64?: string;
  text?: string;
  previewUrl?: string;
}

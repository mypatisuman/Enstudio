import type { ISANodeData } from '../../components/canvas/ISANodes';

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  kind_detail?: string;
  x: number;
  y: number;
  area?: string;
  drawing?: string;
  equipment_ref?: string;
  category?: string;
  type?: string;   // raw detector type, e.g. "Inlet"/"Outlet"
  vendor?: string;
  modelFamily?: string;
  specifications?: Record<string, any>;
  specStatus?: string;
  loop?: string;
  source_id?: number;
  page?: number;
  page_w?: number;
  page_h?: number;
}

export type EdgeProvenance = 'geometry' | 'llm';

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  waypoints?: [number, number][];
  bend_x?: number;
  bend_y?: number;
  source_id?: number;
  provenance?: EdgeProvenance;
  audited?: boolean;
  label?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  pageImage?: string;
  sessionId?: string;
  revision?: number;
  projectType?: string;
}

export type CData = ISANodeData;

import type { GraphNode, GraphEdge } from '../canvas/types';

export interface Instrument {
  id?: string;
  tag: string;
  type: string;
  kind?: string;
  kind_detail?: string;
  drawing?: string;
  equipment_ref?: string;
  area?: string;
  confidence: number;
  review_status?: 'pending' | 'accepted' | 'rejected' | string;
  description?: string;
}

export interface Equipment {
  id?: string;
  tag: string;
  type: string;
  kind?: string;
  drawing?: string;
  area?: string;
  confidence?: number;
  review_status?: 'pending' | 'accepted' | 'rejected' | string;
  description?: string;
}

export type Severity = 'critical' | 'warning' | 'info';
export type IssueStatus = 'open' | 'ignored' | 'resolved';

export interface ValidationIssue {
  id: string;
  ruleId: string;
  severity: Severity;
  category: 'equipment' | 'instrument' | 'connection' | 'symbol';
  title: string;
  description: string;
  tag?: string;
  drawing?: string;
  suggestion?: string;
}

export interface ValidationContext {
  nodes: GraphNode[];
  edges: GraphEdge[];
  instruments: Instrument[];
  equipment: Equipment[];
  nodeById: Map<string, GraphNode>;
  connectedIds: Set<string>;
}

export interface ValidationRule {
  id: string;
  label: string;
  severity: Severity;
  execute(ctx: ValidationContext): ValidationIssue[];
}

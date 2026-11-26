// Typed invoke wrappers for src-tauri/src/commands/graph.rs.

import { invoke } from '@tauri-apps/api/core'
import type {
  GraphData, BatchInsertResult, InsertedNodeId, InsertedJunctionId,
  EdgeInsertResult,
} from './types'

export function getGraph(projectId: string): Promise<GraphData> {
  return invoke('get_graph', { projectId })
}

export function batchInsertNodes(projectId: string, nodesJson: string): Promise<BatchInsertResult<InsertedNodeId>> {
  return invoke('batch_insert_nodes', { projectId, nodesJson })
}

export function batchInsertJunctions(projectId: string, junctionsJson: string): Promise<BatchInsertResult<InsertedJunctionId>> {
  return invoke('batch_insert_junctions', { projectId, junctionsJson })
}

export function batchInsertEdges(projectId: string, edgesJson: string): Promise<EdgeInsertResult> {
  return invoke('batch_insert_edges', { projectId, edgesJson })
}

export function insertEdgeById(projectId: string, fromId: string, toId: string, kind: string): Promise<void> {
  return invoke('insert_edge_by_id', { projectId, fromId, toId, kind })
}

export function updateNodeByTag(
  projectId: string,
  tag: string,
  newTag?: string | null,
  kind?: string | null,
  area?: string | null,
  description?: string | null,
): Promise<void> {
  return invoke('update_node_by_tag', { projectId, tag, newTag, kind, area, description })
}

export function deleteNodeByTag(projectId: string, tag: string): Promise<void> {
  return invoke('delete_node_by_tag', { projectId, tag })
}

export function updateNode(
  projectId: string, nodeId: string, label: string, kind: string, area: string, description: string,
): Promise<void> {
  return invoke('update_node', { projectId, nodeId, label, kind, area, description })
}

export function updateEdgeBend(projectId: string, fromId: string, toId: string, x: number, y: number): Promise<void> {
  return invoke('update_edge_bend', { projectId, fromId, toId, x, y })
}

export function clearEdgeBend(projectId: string, fromId: string, toId: string): Promise<void> {
  return invoke('clear_edge_bend', { projectId, fromId, toId })
}

export function updateNodePosition(projectId: string, nodeId: string, x: number, y: number): Promise<void> {
  return invoke('update_node_position', { projectId, nodeId, x, y })
}

export function deleteEdgeById(projectId: string, fromId: string, toId: string): Promise<void> {
  return invoke('delete_edge_by_id', { projectId, fromId, toId })
}

export function deleteNode(projectId: string, nodeId: string): Promise<void> {
  return invoke('delete_node', { projectId, nodeId })
}

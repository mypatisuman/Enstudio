// Typed invoke wrappers for src-tauri/src/commands/hierarchy.rs — the plant
// hierarchy (site > plant > unit > area > system > subsystem) shared with the
// Python backend's services/hierarchy.py.

import { invoke } from '@tauri-apps/api/core'

export interface HierarchyNode {
  id: number
  level: 'site' | 'plant' | 'unit' | 'area' | 'system' | 'subsystem' | string
  name: string
  direct_nodes: number
  total_nodes: number
  children: HierarchyNode[]
}

export interface HierarchyTree {
  roots: HierarchyNode[]
  unassigned_nodes: number
}

export function getHierarchy(projectId: string): Promise<HierarchyTree> {
  return invoke('get_hierarchy', { projectId })
}

/** node id -> hierarchy entry id */
export function getNodeHierarchy(projectId: string): Promise<Record<string, number>> {
  return invoke('get_node_hierarchy', { projectId })
}

export function assignNodeHierarchy(projectId: string, nodeId: string, hierarchyId: number | null): Promise<void> {
  return invoke('assign_node_hierarchy', { projectId, nodeId, hierarchyId })
}

export function createSubsystem(projectId: string, system: string, subsystem: string, area?: string): Promise<number> {
  return invoke('create_subsystem', { projectId, system, subsystem, area: area || null })
}

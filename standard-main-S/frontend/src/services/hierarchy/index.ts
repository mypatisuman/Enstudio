// Plant hierarchy feature service — the Sidebar hierarchy panel goes through
// here instead of calling invoke() directly.

import * as api from '../invoke/hierarchy'
export type { HierarchyNode, HierarchyTree } from '../invoke/hierarchy'

export const getHierarchy = api.getHierarchy
export const getNodeHierarchy = api.getNodeHierarchy
export const assignNodeHierarchy = api.assignNodeHierarchy
export const createSubsystem = api.createSubsystem

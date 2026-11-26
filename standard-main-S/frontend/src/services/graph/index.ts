// Graph feature service — CanvasScreen's/DescribeScreen's graph read/write
// workflow goes through here instead of calling invoke() directly. Kept as
// a thin pass-through this phase (Phase 5); consolidating the repeated
// "mutate local state -> call service -> push undo -> reload" pattern inside
// CanvasScreen itself is out of scope here per Phase 5's rule against
// refactoring the large screen components.

import * as api from '../invoke/graph'
export type { GraphData, GraphNode, GraphEdge, BatchInsertResult, InsertedNodeId, InsertedJunctionId, EdgeInsertResult } from '../invoke/types'

export const getGraph = api.getGraph
export const batchInsertNodes = api.batchInsertNodes
export const batchInsertJunctions = api.batchInsertJunctions
export const batchInsertEdges = api.batchInsertEdges
export const insertEdgeById = api.insertEdgeById
export const updateNodeByTag = api.updateNodeByTag
export const deleteNodeByTag = api.deleteNodeByTag
export const updateNode = api.updateNode
export const updateEdgeBend = api.updateEdgeBend
export const clearEdgeBend = api.clearEdgeBend
export const updateNodePosition = api.updateNodePosition
export const deleteEdgeById = api.deleteEdgeById
export const deleteNode = api.deleteNode

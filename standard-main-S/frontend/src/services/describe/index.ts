// Describe feature service — DescribeScreen's chat/session persistence and
// graph-editing workflow goes through here instead of calling invoke()
// directly. Thin pass-through this phase; DescribeScreen's own LLM-calling
// and graph-editing logic stays untouched per Phase 5's scope.

import * as api from '../invoke/describe'
import { getGraph, batchInsertNodes, batchInsertJunctions, batchInsertEdges, updateNodeByTag, updateNodePosition, deleteNodeByTag } from '../invoke/graph'
import { readAttachment } from '../invoke/misc'
export type { DescribeSession, DescribeMessageRow } from '../invoke/types'
export type { SaveDescribeMessageArgs, DescribeAgentResult, DescribeAgentOp } from '../invoke/describe'
export type { RawAttachment } from '../invoke/misc'

export const listDescribeSessions = api.listDescribeSessions
export const createDescribeSession = api.createDescribeSession
export const getDescribeMessages = api.getDescribeMessages
export const saveDescribeMessage = api.saveDescribeMessage
export const resolveDescribeDelete = api.resolveDescribeDelete
// Agentic Describe — the backend's eight specialists, reachable from the UI.
export const describeAgentTurn = api.describeAgentTurn
export const describeAgentResolve = api.describeAgentResolve
export const renameDescribeSession = api.renameDescribeSession
export const deleteDescribeSession = api.deleteDescribeSession

// Graph reads/writes Describe needs while composing an LLM turn — re-exported
// here so DescribeScreen has one service import instead of two.
export { getGraph, batchInsertNodes, batchInsertJunctions, batchInsertEdges, updateNodeByTag, updateNodePosition, deleteNodeByTag }

// Generic file read (base64) for the attach feature — one read command reused
// for images/PDF/text/docx; format-specific handling lives in features/describe/attachments.
export { readAttachment }

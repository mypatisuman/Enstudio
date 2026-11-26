// Typed invoke wrappers for src-tauri/src/commands/review.rs.

import { invoke } from '@tauri-apps/api/core'
import type {
  Instrument, Equipment, GapsData, NodeKinds,
  ReviewStatusResponse, BulkReviewResponse, UpdateInstrumentResponse,
  AddConnectionResponse, TagResponse,
} from './types'

export function getInstruments(projectId: string): Promise<Instrument[]> {
  return invoke('get_instruments', { projectId })
}

export function getEquipment(projectId: string): Promise<Equipment[]> {
  return invoke('get_equipment', { projectId })
}

export function getGaps(projectId: string): Promise<GapsData> {
  return invoke('get_gaps', { projectId })
}

export function updateReviewStatus(projectId: string, tag: string, status: string): Promise<ReviewStatusResponse> {
  return invoke('update_review_status', { projectId, tag, status })
}

export function bulkUpdateReview(projectId: string, tags: string[], status: string): Promise<BulkReviewResponse> {
  return invoke('bulk_update_review', { projectId, tags, status })
}

export function updateInstrument(projectId: string, tag: string, field: string, value: string): Promise<UpdateInstrumentResponse> {
  return invoke('update_instrument', { projectId, tag, field, value })
}

export function addConnection(projectId: string, sourceTag: string, targetTag: string, connType: string): Promise<AddConnectionResponse> {
  return invoke('add_connection', { projectId, sourceTag, targetTag, connType })
}

export function deleteInstrument(projectId: string, tag: string): Promise<TagResponse> {
  return invoke('delete_instrument', { projectId, tag })
}

export function getNodeKinds(): Promise<NodeKinds> {
  return invoke('get_node_kinds')
}

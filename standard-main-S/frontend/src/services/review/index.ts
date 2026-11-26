// Review feature service — ReviewScreen's instrument/equipment review
// workflow goes through here instead of calling invoke() directly.

import * as api from '../invoke/review'
export type {
  Instrument, Equipment, GapsData, GapRow, NoDrawingRow, LowConfidenceRow, NodeKinds,
  ReviewStatusResponse, BulkReviewResponse, UpdateInstrumentResponse, AddConnectionResponse, TagResponse,
} from '../invoke/types'

export const getInstruments = api.getInstruments
export const getEquipment = api.getEquipment
export const getGaps = api.getGaps
export const updateReviewStatus = api.updateReviewStatus
export const bulkUpdateReview = api.bulkUpdateReview
export const updateInstrument = api.updateInstrument
export const addConnection = api.addConnection
export const deleteInstrument = api.deleteInstrument
export const getNodeKinds = api.getNodeKinds

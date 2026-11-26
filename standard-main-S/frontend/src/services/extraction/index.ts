// Extraction feature service — wraps the run/cancel commands ExtractionContext
// orchestrates. ExtractionContext's own state machine (progress log, per-
// project tracking, event listening) is untouched per Phase 5's scope; only
// its two direct invoke() calls move behind this service.

import * as api from '../invoke/extraction'

export const runExtraction = api.runExtraction
export const cancelExtraction = api.cancelExtraction

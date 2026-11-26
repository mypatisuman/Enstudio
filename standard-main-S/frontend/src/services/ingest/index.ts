// Ingest feature service — IngestScreen's upload/source workflow goes
// through here instead of calling invoke() directly.

import * as api from '../invoke/ingest'
import { getSourceDataUrl } from '../invoke/misc'
export type { Source, NativeUploadResult } from '../invoke/types'

export const getSources = api.getSources
export const nativeUploadFile = api.nativeUploadFile
export { getSourceDataUrl }

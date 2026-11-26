// Typed invoke wrappers for src-tauri/src/commands/ingest.rs.

import { invoke } from '@tauri-apps/api/core'
import type { Source, NativeUploadResult } from './types'

export function getSources(projectId: string): Promise<Source[]> {
  return invoke('get_sources', { projectId })
}

export function nativeUploadFile(projectId: string, filePath: string): Promise<NativeUploadResult> {
  return invoke('native_upload_file', { projectId, filePath })
}

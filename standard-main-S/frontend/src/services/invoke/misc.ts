// Typed invoke wrappers for src-tauri/src/commands/misc.rs.

import { invoke } from '@tauri-apps/api/core'
import type { PageImageResult } from './types'

export function getSourceDataUrl(projectId: string, filename: string): Promise<string> {
  return invoke('get_source_data_url', { projectId, filename })
}

export function getPageImagePath(projectId: string, page?: number): Promise<PageImageResult> {
  return invoke('get_page_image_path', { projectId, page })
}

export interface RawAttachment { name: string; ext: string; data: string; size: number }

export function readAttachment(filePath: string): Promise<RawAttachment> {
  return invoke('read_attachment', { filePath })
}

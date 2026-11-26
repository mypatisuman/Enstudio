// Typed invoke wrappers for src-tauri/src/commands/export.rs.

import { invoke } from '@tauri-apps/api/core'

export function getExportStatus(projectId: string): Promise<string[]> {
  return invoke('get_export_status', { projectId })
}

export function getExportContent(projectId: string, filename: string): Promise<string> {
  return invoke('get_export_content', { projectId, filename })
}

export function previewExport(projectId: string, format: string): Promise<string> {
  return invoke('preview_export', { projectId, format })
}

/**
 * ISA-5.1 vector SVG (real geometry, not a Canvas capture).
 * Defaults to the light background: an export is printed and marked up on
 * paper, where the Canvas's dark ground would come out a solid black sheet.
 */
export function fetchSvgExport(
  projectId: string, view = 'control', background = 'light',
  positions?: string,
): Promise<string> {
  return invoke('fetch_svg_export', { projectId, view, background, positions })
}

export function openPathInOs(path: string): Promise<void> {
  return invoke('open_path_in_os', { path })
}

export function saveExportToPath(content: string, path: string): Promise<void> {
  return invoke('save_export_to_path', { content, path })
}

export function exportDxfNative(projectId: string): Promise<string> {
  return invoke('export_dxf_native', { projectId })
}

export function previewDxfNative(projectId: string): Promise<string> {
  return invoke('preview_dxf_native', { projectId })
}

export type ConnectivitySchema = '2.0.0' | '2.1.0'

export interface ExportFileResult { success: boolean; filename: string; path: string }

/** Writes <pid>_connectivity[_2_1_0].json to the hub's exports folder. */
export function exportConnectivity(projectId: string, schemaVersion: ConnectivitySchema = '2.0.0'): Promise<ExportFileResult> {
  return invoke('export_connectivity', { projectId, schemaVersion })
}

/** The connectivity graph JSON as text. 2.1.0 adds each node's system and subsystem. */
export function previewConnectivity(projectId: string, schemaVersion: ConnectivitySchema = '2.0.0'): Promise<string> {
  return invoke('preview_connectivity', { projectId, schemaVersion })
}

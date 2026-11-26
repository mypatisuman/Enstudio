// Typed invoke wrappers for src-tauri/src/commands/projects.rs.

import { invoke } from '@tauri-apps/api/core'
import type { Project, CreateProjectResponse, ProjectStats, RenameProjectResponse, SuccessResponse } from './types'

export function listProjects(userId: number | null | undefined): Promise<Project[]> {
  return invoke('list_projects', { userId })
}

export function createProject(name: string, userId: number | null | undefined): Promise<CreateProjectResponse> {
  return invoke('create_project', { name, userId })
}

export function getProjectStats(projectId: string): Promise<ProjectStats> {
  return invoke('get_project_stats', { projectId })
}

export function renameProject(projectId: string, newName: string): Promise<RenameProjectResponse> {
  return invoke('rename_project', { projectId, newName })
}

export function deleteProject(projectId: string): Promise<SuccessResponse> {
  return invoke('delete_project', { projectId })
}

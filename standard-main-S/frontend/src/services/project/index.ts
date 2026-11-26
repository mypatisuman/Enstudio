// Project feature service — Sidebar's project list/CRUD workflows go through
// here instead of calling invoke() directly.

import * as api from '../invoke/projects'
export type { Project, CreateProjectResponse, ProjectStats, RenameProjectResponse, SuccessResponse } from '../invoke/types'

export const listProjects = api.listProjects
export const createProject = api.createProject
export const getProjectStats = api.getProjectStats
export const renameProject = api.renameProject
export const deleteProject = api.deleteProject

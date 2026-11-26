// Typed invoke wrapper for src-tauri/src/commands/misc.rs::get_usage_history.

import { invoke } from '@tauri-apps/api/core'
import type { UsageRecord } from './types'

export function getUsageHistory(userId: number | null | undefined): Promise<UsageRecord[]> {
  return invoke('get_usage_history', { userId })
}

export function deleteProjectUsage(pid: string): Promise<void> {
  return invoke('delete_project_usage', { pid })
}

export function deleteUsageScan(pid: string, scanIndex: number): Promise<void> {
  return invoke('delete_usage_scan', { pid, scanIndex })
}

export function addUsageScan(pid: string, provider: string, model: string, tokensIn: number, tokensOut: number, costUsd: number): Promise<void> {
  return invoke('add_usage_scan', { pid, provider, model, tokensIn, tokensOut, costUsd })
}

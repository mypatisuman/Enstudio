// Usage feature service — UsageScreen's key/model config + cost history
// workflow goes through here instead of calling invoke() directly.

import { getUsageHistory, deleteProjectUsage, deleteUsageScan } from '../invoke/usage'
export type { UsageRecord } from '../invoke/types'
import * as llmConfig from '../llmConfig'

export { getUsageHistory, deleteProjectUsage, deleteUsageScan }
export const {
  getCredentialStatus, saveApiKey, getModels, saveModels,
  saveGeminiKey, getGeminiModel, saveGeminiModel,
  saveOpenaiKey, getOpenaiModel, saveOpenaiModel,
  getLlmProvider, saveLlmProvider,
  getCustomProviders, saveCustomProvider, removeCustomProvider,
} = llmConfig

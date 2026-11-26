// LLM provider config feature service — shared by Ingest, Describe, and
// Usage screens, all of which independently read/write the active
// provider's API key/model/credentials. Thin pass-through this phase;
// consolidating the three screens' near-identical loading logic into a
// shared hook is Phase 6+ work (frontend shared domain logic), not this one.

import * as api from '../invoke/config'

// Phase 0: the key GETTERS are gone — a credential must never reach the
// renderer. Saving a key is still fine (it travels one way, into the
// encrypted store); reading one back is not. Use getCredentialStatus() when
// you only need to know whether a key exists.
export const getApiKeyStatus = api.getApiKeyStatus
export const getCredentialStatus = api.getCredentialStatus
export const saveApiKey = api.saveApiKey
export const getModels = api.getModels
export const saveModels = api.saveModels
export const saveGeminiKey = api.saveGeminiKey
export const getGeminiModel = api.getGeminiModel
export const saveGeminiModel = api.saveGeminiModel
export const saveOpenaiKey = api.saveOpenaiKey
export const getOpenaiModel = api.getOpenaiModel
export const saveOpenaiModel = api.saveOpenaiModel
export const getLlmProvider = api.getLlmProvider
export const saveLlmProvider = api.saveLlmProvider
export const getCustomProviders = api.getCustomProviders
export const saveCustomProvider = api.saveCustomProvider
export const removeCustomProvider = api.removeCustomProvider
export type { CustomProviderRow, CredentialStatus } from '../invoke/config'

import { createContext, useContext } from 'react'
import { emptyState } from './extraction/types'
import type { ExtractionCtx, ExtractionCtxValue } from './extraction/types'

export const Ctx = createContext<ExtractionCtxValue | null>(null)

export function useExtraction(projectId: string): ExtractionCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useExtraction must be used inside ExtractionProvider')
  const slice = ctx.byProject[projectId] ?? emptyState()
  return {
    ...slice,
    projectId,
    start:  (sourceId: number, llmOnly?: boolean) => ctx.start(projectId, sourceId, llmOnly),
    cancel: () => ctx.cancel(projectId),
    reset:  () => ctx.reset(projectId),
  }
}

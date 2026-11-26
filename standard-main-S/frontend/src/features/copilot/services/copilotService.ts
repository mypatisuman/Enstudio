import type { LlmCredentials } from '../../describe/utils/llmClient'
import type { CopilotMessage, CopilotResult } from '../types'
import { getProjectContext, getSummary, setSummary, type ProjectContext } from '../context/projectContext'
import { COPILOT_SYSTEM_PROMPT } from '../prompts/systemPrompt'
import { buildCopilotMessages } from '../prompts/buildMessages'
import { resolveIntent } from '../actions/intents'
import { buildSearchItems, runSearch, toResults, type SearchItem } from '../actions/search'
import { streamLlm } from './llmStream'
import { addUsageScan } from '../../../services/invoke/usage'
import { planCommand, type CommandPreview, type CommandRequest } from '../../engineeringCommands'

// Single public entry point for the Copilot. Every AI feature (search, focus,
// explain, summary, validation Q&A, general questions, destructive previews)
// routes through ask(). Future AI features reuse this service.

export interface AskDeps {
  projectId: string
  projectName: string
  history: CopilotMessage[]
  creds: LlmCredentials
  focus: (tag: string) => void                 // QUEUE a FocusBus tag (no navigation)
  onToken: (chunk: string) => void             // streamed assistant text
}

export interface AskResult {
  content: string
  results?: CopilotResult[]
  pending?: CommandPreview                       // an editing command awaiting Confirm/Cancel
  navigatedTo?: string
  navigate?: boolean                           // screen should switch to Canvas after committing
}

// Turn a planned command into an ask result: an error message, or a preview the
// panel renders with Confirm/Cancel. Never mutates — planCommand only previews.
function editResult(req: CommandRequest, ctx: ProjectContext): AskResult {
  const preview = planCommand(req, ctx)
  if (preview.error) return { content: `⚠️ ${preview.error}` }
  return { content: `**${preview.title}** — review the preview below, then Confirm or Cancel.`, pending: preview }
}

function disconnectedTags(ctx: ProjectContext): Set<string> {
  return new Set(
    ctx.issues
      .filter(i => i.ruleId === 'disconnected-equipment' || i.ruleId === 'disconnected-instruments')
      .map(i => i.tag)
      .filter((t): t is string => !!t),
  )
}

// Build a compact, grounded detail block for one object — its neighbours (from
// edges) and any validation issues — so the LLM explains real data, not guesses.
function objectDetail(ctx: ProjectContext, tag: string): string {
  const node = ctx.nodes.find(n => n.label === tag)
  const idByLabel = new Map(ctx.nodes.map(n => [n.label, n.id]))
  const labelById = new Map(ctx.nodes.map(n => [n.id, n.label]))
  const id = idByLabel.get(tag)
  const neighbours = id
    ? ctx.edges
        .filter(e => e.source === id || e.target === id)
        .map(e => {
          const other = e.source === id ? labelById.get(e.target) : labelById.get(e.source)
          return `${other ?? '?'} (${e.kind || 'stream'})`
        })
    : []
  const instr = ctx.instruments.find(i => i.tag === tag)
  const equip = ctx.equipment.find(e => e.tag === tag)
  const issues = ctx.issues.filter(i => i.tag === tag)
  return [
    `OBJECT: ${tag}`,
    node && `kind: ${node.kind_detail || node.kind || node.category}`,
    (instr || equip) && `type: ${instr?.type || equip?.type || '—'}`,
    (instr?.drawing || equip?.drawing) && `drawing: ${instr?.drawing || equip?.drawing}`,
    instr?.equipment_ref && `equipment reference: ${instr.equipment_ref}`,
    instr && instr.confidence > 0 && `confidence: ${Math.round(instr.confidence * 100)}%`,
    (instr?.description || equip?.description) && `description: ${instr?.description || equip?.description}`,
    `connections (${neighbours.length}): ${neighbours.join(', ') || 'none'}`,
    issues.length ? `validation issues: ${issues.map(i => `[${i.severity}] ${i.title}`).join('; ')}` : 'validation issues: none',
  ].filter(Boolean).join('\n')
}

function severityLine(ctx: ProjectContext): string {
  const v = ctx.validation
  return `${v.total} issues — ${v.critical} critical, ${v.warning} warning, ${v.info} info.`
}

// Thin wrapper around streamLlm that also logs the turn's usage — every
// Copilot call (explain/summary/general Q&A) routes through here so none of
// them silently skip cost tracking the way they used to.
async function streamAndLogUsage(
  system: string, apiMessages: { role: string; content: string }[], deps: AskDeps,
): Promise<string> {
  const { content, usage } = await streamLlm(system, apiMessages, deps.creds, deps.onToken)
  addUsageScan(deps.projectId, usage.provider, usage.model, usage.tokensIn, usage.tokensOut, usage.costUsd).catch(console.error)
  return content
}

export async function ask(text: string, deps: AskDeps): Promise<AskResult> {
  const intent = resolveIntent(text)
  const ctx = await getProjectContext(deps.projectId, deps.projectName)
  const items = buildSearchItems(ctx)

  switch (intent.kind) {
    case 'search': {
      const filter = { ...intent.filter }
      if (filter.disconnectedTags) filter.disconnectedTags = disconnectedTags(ctx)
      const hits = runSearch(items, filter)
      const results = toResults(hits)
      const content = hits.length
        ? `Found **${hits.length}** ${filter.label}. Click any result to focus it on the Canvas.`
        : `No ${filter.label} found in this project.`
      return { content, results: results.length ? results : undefined }
    }

    case 'focus': {
      const hit = items.find(i => i.tag.toLowerCase() === intent.tag.toLowerCase())
      if (!hit) return { content: `No object tagged **${intent.tag}** in this project.` }
      deps.focus(hit.tag)
      return { content: `Focusing on **${hit.tag}** — opening the Canvas.`, navigatedTo: hit.tag, navigate: true }
    }

    case 'validation': {
      let issues = ctx.issues
      if (intent.severity) issues = issues.filter(i => i.severity === intent.severity)
      const results = issues.filter(i => i.tag).map(i => ({
        tag: i.tag!, title: i.title, detail: `${i.severity}${i.drawing ? ` · Drawing ${i.drawing}` : ''}`,
      }))
      if (intent.count) {
        const label = intent.severity ? `${intent.severity} issue${issues.length === 1 ? '' : 's'}` : 'issues'
        return { content: `There ${issues.length === 1 ? 'is' : 'are'} **${issues.length}** ${label}. ${severityLine(ctx)}` }
      }
      const list = issues.slice(0, 25).map(i => `- **[${i.severity}]** ${i.title}`).join('\n')
      const content = issues.length
        ? `${severityLine(ctx)}\n\n${list}${issues.length > 25 ? `\n\n_…and ${issues.length - 25} more._` : ''}`
        : `No matching validation issues. ${severityLine(ctx)}`
      return { content, results: results.length ? results : undefined }
    }

    case 'rename':      return editResult({ kind: 'rename', tag: intent.tag, newTag: intent.newTag }, ctx)
    case 'rename-bulk': return editResult({ kind: 'rename-bulk', fromPrefix: intent.fromPrefix, toPrefix: intent.toPrefix }, ctx)
    case 'move':        return editResult({ kind: 'move', tag: intent.tag, anchorTag: intent.anchorTag, dir: intent.dir }, ctx)
    case 'delete':      return editResult({ kind: 'delete-node', tags: intent.tags }, ctx)
    case 'delete-unused': return editResult({ kind: 'delete-unused' }, ctx)
    case 'disconnect':  return editResult({ kind: 'disconnect', tag: intent.tag }, ctx)
    case 'connect':     return editResult({ kind: 'create-connection', source: intent.source, target: intent.target, connType: 'stream' }, ctx)
    case 'duplicate':   return editResult({ kind: 'duplicate', tag: intent.tag }, ctx)

    case 'layout': {
      const tags = runSearch(items, intent.filter).map(i => i.tag)
      if (tags.length < 2) return { content: `Need at least two ${intent.filter.label} to ${intent.op}. Found ${tags.length}.` }
      const req: CommandRequest = intent.op === 'auto-layout'
        ? { kind: 'auto-layout', tags }
        : { kind: intent.op, tags, axis: intent.axis }
      return editResult(req, ctx)
    }

    case 'explain': {
      const hit = items.find(i => i.tag.toLowerCase() === intent.tag.toLowerCase())
      if (!hit) return { content: `No object tagged **${intent.tag}** to explain.` }
      deps.focus(hit.tag)   // queue only — stays on Copilot so the explanation streams in place
      const request = `Explain the object below for a process engineer. Use the Purpose / Working Principle / Connections / Signals / Engineering Notes / Related Equipment / Validation Issues / Confidence structure, omitting sections the data can't support.\n\n${objectDetail(ctx, hit.tag)}`
      const { system, apiMessages } = buildCopilotMessages(COPILOT_SYSTEM_PROMPT, ctx, deps.history, request)
      const content = await streamAndLogUsage(system, apiMessages, deps)
      return { content, navigatedTo: hit.tag }
    }

    case 'summary': {
      const key = `${deps.projectId}:${intent.drawing ?? 'all'}`
      const cached = getSummary(key)
      if (cached) { deps.onToken(cached); return { content: cached } }
      const scope = intent.drawing ? `Drawing ${intent.drawing}` : 'this project'
      const request = `Produce a drawing summary for ${scope} using the sections: Overview, Major Equipment, Instrumentation, Process Flow, Control Strategy, Utilities, Validation Summary, Engineering Risks, Unknown Objects. Base everything only on the project context.`
      const { system, apiMessages } = buildCopilotMessages(COPILOT_SYSTEM_PROMPT, ctx, deps.history, request)
      const content = await streamAndLogUsage(system, apiMessages, deps)
      setSummary(key, content)
      return { content }
    }

    default: {
      const { system, apiMessages } = buildCopilotMessages(COPILOT_SYSTEM_PROMPT, ctx, deps.history, text)
      const content = await streamAndLogUsage(system, apiMessages, deps)
      return { content }
    }
  }
}

export type { SearchItem }

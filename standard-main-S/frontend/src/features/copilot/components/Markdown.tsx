import { Fragment, type ReactNode } from 'react'

// Minimal, dependency-free markdown for chat replies. Handles the subset the
// assistant actually emits: headings, bold, inline code, fenced code blocks,
// bullet/numbered lists, blockquotes and paragraphs. Builds React nodes (never
// dangerouslySetInnerHTML) so model output can't inject markup.
// ponytail: covers the emitted subset; reach for a real md lib only if replies
// start needing tables/images.

function inline(text: string, keyBase: string): ReactNode[] {
  // Split on **bold** and `code`, keeping delimiters via capture groups.
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <strong key={`${keyBase}-${i}`}>{p.slice(2, -2)}</strong>
    if (p.startsWith('`') && p.endsWith('`')) return <code key={`${keyBase}-${i}`} className="cop-code">{p.slice(1, -1)}</code>
    return <Fragment key={`${keyBase}-${i}`}>{p}</Fragment>
  })
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, '').split('\n')
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let code: string[] | null = null

  const flushList = () => {
    if (!list) return
    const key = `l${blocks.length}`
    blocks.push(
      list.ordered
        ? <ol key={key} className="cop-md-ol">{list.items.map((it, i) => <li key={i}>{inline(it, `${key}-${i}`)}</li>)}</ol>
        : <ul key={key} className="cop-md-ul">{list.items.map((it, i) => <li key={i}>{inline(it, `${key}-${i}`)}</li>)}</ul>,
    )
    list = null
  }

  for (const raw of lines) {
    const line = raw

    if (line.trim().startsWith('```')) {
      if (code) { blocks.push(<pre key={`c${blocks.length}`} className="cop-pre"><code>{code.join('\n')}</code></pre>); code = null }
      else { flushList(); code = [] }
      continue
    }
    if (code) { code.push(line); continue }

    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      flushList()
      const lvl = h[1].length
      const key = `h${blocks.length}`
      blocks.push(<div key={key} className={`cop-h cop-h${lvl}`}>{inline(h[2], key)}</div>)
      continue
    }

    const ul = /^\s*[-*]\s+(.*)$/.exec(line)
    const ol = /^\s*\d+\.\s+(.*)$/.exec(line)
    if (ul || ol) {
      const ordered = !!ol
      if (!list || list.ordered !== ordered) { flushList(); list = { ordered, items: [] } }
      list.items.push((ul ?? ol)![1])
      continue
    }

    if (!line.trim()) { flushList(); continue }

    flushList()
    const key = `p${blocks.length}`
    blocks.push(<p key={key} className="cop-p">{inline(line, key)}</p>)
  }
  flushList()
  if (code) blocks.push(<pre key="cend" className="cop-pre"><code>{code.join('\n')}</code></pre>)

  return <div className="cop-md">{blocks}</div>
}

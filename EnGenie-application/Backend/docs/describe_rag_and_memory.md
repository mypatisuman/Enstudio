# P&ID chat: input analysis, RAG answers and context memory

The Describe chat (P&ID Studio drawer and `PIDDescribePage`) is one conversation in which an
engineer both **builds or changes** a P&ID and **asks questions** about the P&ID that was built.
Every message is analysed first and sent down the right path.

## Flow of one message

```
POST /api/pid/describe
  └─ run_describe_turn (agents/describe/workflows/describe_workflow.py)
       1. chat memory: load, fold messages older than the window into the summary
       2. pending clarification?  -> answered as before (holistic / subsystem gates)
       3. input analysis          -> mode + standalone steps
       4. per step
            change   -> router -> brownfield check -> holistic + subsystem gates -> specialist
            question -> Query agent (retrieval-augmented) or Validation agent
       5. answers: cited [TAG]s checked against the drawing
       6. chat memory: focus tags, change log, turn record
```

A **mixed** message ("add PI-102 and tell me what is connected to V-101") runs the change first,
then answers on the updated drawing. If the change stops on a clarifying question, the question
steps are still answered and the clarifying question comes last. A pending deletion confirmation
stops the turn.

## Modules

| Module | Role |
|---|---|
| `agents/describe/services/turn_analysis.py` | build / update / question / mixed / chat. Rules first; the LLM (`describe_turn_analysis.md`) refines when the rules are not certain (several steps, a pronoun to resolve, no verb). Rewrites follow-ups as standalone steps. |
| `agents/describe/services/chat_memory.py` | Dynamic context memory per (project, session), built afresh for every request within a token budget (see below). Shown to every specialist as the transcript plus a `CHAT MEMORY` block. |
| `domain/pid_rag/snapshot.py` | One view of a drawing from studio.db (describe graph, hierarchy, designed solution, digitisation meta) or from a solution-session `PIDGraph` (Mongo). |
| `domain/pid_rag/cards.py` | Knowledge cards: drawing, plant group, equipment, instrument, flag, loop, process run, design rationale, review notes. |
| `domain/pid_rag/index.py` | Cards embedded with the hosted embedding model, stored next to the graph; only changed cards are re-embedded. Refreshed lazily on the first question after a change. |
| `domain/pid_rag/retriever.py` | Hybrid retrieval (exact tags + vectors + keywords) with one-hop expansion; `trace_path`, `count_elements`. |
| `domain/pid_rag/citations.py` | `[TAG]` citations must exist on the drawing; unknown ones are un-bracketed and named. |
| `domain/pid_rag/answer.py` | One-shot grounded answer for drawings outside the Describe chat (`/api/pid/ask`). |
| `agents/describe/agents/query_agent.py` | Query agent with `retrieve_pid_context`, `trace_path`, `count_elements` and the exact graph tools (`describe_query.md`). |

## Dynamic context memory

No fixed message counts. For each request:

1. **Budget**: `budget_for(fixed)` = model context (`DESCRIBE_MODEL_CONTEXT_TOKENS`, default 32768)
   − reply reserve − tool-result reserve − the tokens this specialist's prompt already uses
   (instructions, graph summary, designed solution, tool list), capped by
   `DESCRIBE_MAX_MEMORY_TOKENS` (default 16000, the cost ceiling).
2. **Recent**: newest messages first until half the budget is used; the last exchange is always
   kept; a single huge message is trimmed head and tail.
3. **Recall**: older messages about the request's tags and words come back verbatim, however far
   back they are (up to a fifth of the budget); then the not-yet-summarised stretch before the
   recent window, newest first, while room is left.
4. **Memory block**, by priority: the episode summaries about this request (then the latest),
   the overall brief, the entities, the changes about this request (then the latest), the
   latest requests.

**Maintenance** (`maintain`, start of each turn) is token-driven: when the messages between the
last episode and the recent window outgrow an episode's share of the budget, they become an
**episode** (LLM summary + its tags); when the episodes grow, the **brief** is refreshed. Nothing
is summarised while the chat still fits.

**Entities** carry scores, not a fixed list: a change adds 1.5, the engineer naming a tag 1.0, an
answer citing it 0.6; scores decay by 0.85 per turn, and tags that have faded out are forgotten.

## Storage (studio.db, created on first use)

- `pid_rag_chunks (pid, chunk_id, kind, tags_json, text, text_hash, embedding, model)`
- `pid_rag_state (pid, content_hash, model, complete, updated_at)`
- `describe_chat_memory (pid, session_id, summary, summarized_upto, focus_json, changes_json, turns_json, episodes_json, updated_at)` (`focus_json` holds the entity scores; a first-version focus list still loads)

The full transcript stays in `describe_session_states` as before.

## API

- `POST /api/pid/describe` returns, in addition to before: `mode`, `analysis`, `citations`,
  `sources`, `steps`, `agent`.
- `POST /api/pid/ask` `{question, session_id?, pid?}`: answers about the describe drawing, or the
  solution session's `PIDGraph` when the project has no describe drawing. Returns `reply`,
  `citations`, `sources`, `mode`, `standalone`.
- `POST /api/pid/rag/reindex` `{pid?, session_id?, full?}`: rebuild the index now.

The chat UI shows a mode badge (Answer / Build / Update / Build + Answer) and the cited tags as
chips that focus the node on the canvas.

## Cost

- One fast-tier LLM call for input analysis, only when the rules are not certain.
- One fast-tier call per new episode, and one per brief refresh, only once older messages no
  longer fit (at most two episodes per turn).
- Embeddings only for cards whose text changed since the last question.
- The Query agent's own calls (retrieval is one tool call).

## Tests

`tests/test_pid_rag.py` (scripted LLM, fake embeddings): snapshot and cards, incremental index,
retrieval, path tracing and counts, citations, input analysis (rules and LLM), memory and summary,
questions, mixed turns and follow-ups end to end, and `/api/pid/ask`.

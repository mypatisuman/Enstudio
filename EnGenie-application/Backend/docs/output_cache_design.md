# Output Cache (Episodic Input→Output Cache) — Design & Revival Reference

> **Status: REMOVED.** This module (`common/ai/memory/output_cache.py`) and its wiring
> were deleted on 2026-06-15. This document captures the full design so it can be
> re-implemented later. Recall of saved projects is now handled by **`episodic_recall`
> + `MongoProjectManager.find_similar_projects`** (see "Why it was removed").

---

## 1. What it was

A generic **per-`(user, page)` input → output cache** with a confirm-before-serve gate.
It detected when a new request was a *repeat* of an earlier one (semantically) and offered
to return the **stored output snapshot** of that earlier request instead of recomputing.

It was seeded **only from saved projects** (not from every agent run), so in practice its
contents were saved-project-derived: for the solution page it stored identified
instruments/accessories; for the search page it stored the saved `searchTabs`.

It powered the **"Repeated Request Detected"** dialog on both the solution and search pages.

---

## 2. Storage schema

MongoDB collection: **`episodic_input_cache`**. One document per `(user_id, page, input_norm_hash)`:

```jsonc
{
  "user_id": "1",                  // str(user_id)
  "page": "solution" | "search",   // logical namespace
  "input_norm_hash": "<sha256>",   // hash of normalized input — UPSERT KEY (not a matcher)
  "input_text": "Design an integrated control system ...",
  "input_embedding": [/* 1024 floats, Qwen/Qwen3-Embedding-0.6B (hosted) */],
  "output": { /* arbitrary page-specific payload returned on retrieve */ },
  "created_at":   ISODate,         // for the "cached from <date>" label only
  "updated_at":   ISODate,
  "last_accessed":ISODate,         // sliding-TTL anchor (refreshed on store + on hit)
  "hit_count":    3                // best-effort stat
}
```

### Indexes (were created in `mongodb_config.create_indexes`)
```python
# exact upsert-key lookup
_safe_create_index(col, [("user_id",1),("page",1),("input_norm_hash",1)], name="idx_cache_hash")
# candidate fetch for semantic match (all of a user's cached inputs for a page)
_safe_create_index(col, [("user_id",1),("page",1)], name="idx_cache_user_page")
# sliding 30-day TTL on last_accessed
_safe_create_index(col, "last_accessed", name="episodic_cache_ttl_30d",
                   expireAfterSeconds=60*60*24*30)
```
The TTL is a **sliding window**: `last_accessed` is bumped on every store and every hit,
so frequently-used entries survive while idle ones expire after 30 days.

---

## 3. Detection algorithm (read path)

**Final design was embeddings-only** (an earlier version had a Tier-1 exact-hash tier that
was dropped). The normalized hash remained only as the write-path upsert key.

```python
def lookup_cached_output(user_id, page, input_text, similarity_threshold=0.95):
    # embed input -> cosine-match against all of the user's cached inputs for `page`
    doc, similarity = _semantic_lookup(col, user_id, page, input_text, similarity_threshold)
    if not doc: return None
    match_type = "exact" if similarity >= 0.999 else "semantic"
    # bump last_accessed + hit_count
    return {output, input_text, cached_at, age_days, match_type, similarity}
```

`_semantic_lookup` loads every candidate doc for `(user_id, page)` that has an
`input_embedding`, then ranks with `embedding_manager.find_most_similar`.

> **Important: rescaled similarity.** `find_most_similar` returns `(cosine + 1) / 2`, so the
> `0.95` threshold == **raw cosine 0.90**. A literally identical input embeds to ~1.0 and
> matches; reworded/reordered same-intent inputs match if their rescaled cosine ≥ 0.95.

Model: `Qwen/Qwen3-Embedding-0.6B` on DeepInfra (hosted LLM embeddings), 1024-dim; similarity mapped onto the former MiniLM scale (see `common/ai/embedding_manager.py`).

---

## 4. Write path (seeding) — only from saved projects

`MongoProjectManager._prepare_episodic_memory(...)` (called at the end of `save_project`)
seeded the cache. Final form (after the substantive-only guards):

```python
# SOLUTION: (removed earlier — solution moved to episodic_recall)
#   store_cached_output(user_id, 'solution', initial_requirements, {
#       'type':'solution','intent':'saved_project','response_type':'solution',
#       'instruments': instruments, 'accessories': accessories,
#       'from_saved_project': True, 'project_id': pid, 'project_name': name })

# SEARCH: one entry per distinct saved search query (requirements + each tab input)
for text, tabs in search_inputs:
    if not tabs:                    # nothing to recall -> drop any stale entry
        delete_cached_output(user_id, 'search', text); continue
    store_cached_output(user_id, 'search', text, {
        'success': True, 'intent': 'savedSearch', 'fromSavedProject': True,
        'productType': product_type, 'searchTabs': tabs,
        'projectId': pid, 'projectName': name })
```

Key write functions:
- `store_cached_output(user_id, page, input_text, output)` — background-thread upsert by
  `(user_id, page, _hash(input_text))`; computes + stores the embedding. No-op for anonymous
  users / empty input / `output is None`.
- `delete_cached_output(user_id, page, input_text)` — background-thread delete of the exact
  normalized-input entry. Added so an emptied re-save drops its stale recall entry (kept the
  cache consistent with the blob).
- `clear_user_cache(user_id)` — delete all of a user's entries.

`_normalize` = lowercase, strip punctuation→space, collapse whitespace. `_hash` = SHA-256 of
the normalized text.

---

## 5. Confirm-before-serve gate

A match did **not** serve directly — it asked first. Pending state lived in a module-global
dict keyed by `session_id` (in-memory, with an eviction callback registered against session
clearing), **not** in Mongo.

```python
store_pending_cache(session_id, input_text, cache_hit)   # hold the match
get_pending_cache(session_id) -> {input_text, cache_hit, timestamp}
clear_pending_cache(session_id)
build_cache_confirmation_prompt(cache_hit) -> "Repeated request - I see that you saved a similar project on <date>. Open - Preview - Ignore"
interpret_cache_reply(reply) -> "retrieve" | "reanalyze"   # lite-LLM, regex fallback
format_cache_label(cache_hit) -> "♻️ Returning a cached result from <date> (<age>). Live pricing ... may have changed."
```

`interpret_cache_reply` used the lite LLM with a deterministic keyword fallback; ambiguous
replies defaulted to **reanalyze** (safer than serving a possibly-wrong cached result).

### Gate flow (as wired into `run_project_intent` / search agent)
```
get_pending_cache(session_id)?
├── YES  -> this message is the reply
│          interpret_cache_reply():
│            "retrieve"  -> serve cache_hit.output + freshness label, return
│            "reanalyze" -> restore ORIGINAL input, fall through to live agent
└── NO   -> lookup_cached_output(user_id, page, input)
             HIT -> store_pending_cache(); return {intent:"cache_confirmation",
                    message, matched_projects:[...from find_similar_projects...]}
```
The dialog list (`matched_projects`) was always built from `find_similar_projects`, and the
dialog's **Open/Preview** buttons fetched the live project via `GET /api/projects/{id}` —
they never read `cache_hit.output`. Only the text-reply "retrieve" branch served the snapshot.

---

## 6. How it was wired (all removed)

| Caller | What it did |
|---|---|
| `agentic_integration.run_project_intent` (solution) | gate + detection — **migrated to `episodic_recall` first**, then this whole module removed |
| `app/api/v1/search.py` (search agent) | gate + detection on fresh `initialInput` queries — removed (search recall dropped) |
| `project_repository._prepare_episodic_memory` | seeding from saves — removed |
| `common/ai/memory/__init__.py` | re-exports + `clear_all_session_data` called `clear_pending_cache` — removed |
| `mongodb_config` | collection registration + 3 indexes — removed |

---

## 7. Why it was removed

It duplicated the job of **`episodic_recall` + `find_similar_projects`**, which match the
request directly against saved **projects** (`user_projects` embeddings) and retrieve the
**live** project via `get_project_details`. The cache's separate `episodic_input_cache`
collection — a *copy* of project-derived state — was the root cause of a whole bug class:

- empty/requirements-only saves seeded empty entries → "Repeated Request Detected" that
  opened to nothing;
- entries went stale when the underlying blob changed (needed seeding guards +
  `delete_cached_output` self-heal);
- two thresholds / two stores could disagree.

Matching projects directly (single source of truth) made all of that disappear. See
`episodic_recall.py` + `MongoProjectManager.find_similar_projects` for the replacement, and
the solution gate in `run_project_intent` for the live pattern.

### Difference vs `episodic_recall`
| | `output_cache` (removed) | `episodic_recall` (current) |
|---|---|---|
| Matches against | separate cache collection | saved projects directly |
| Returns | stored output **snapshot** (can be stale → freshness label) | **live** project via `get_project_details` |
| Extra ability | true **skip-recompute** cache | none — always re-fetches |

---

## 8. When to re-implement it

Bring it back **only as a pure recompute-avoidance cache** — i.e. to skip re-running an
expensive agent for a genuinely identical request — and keep it **decoupled from recall**
(recall stays on `episodic_recall`). Revival steps:

1. Recreate `common/ai/memory/output_cache.py` from sections 2–5 above (schema, embeddings-only
   `lookup_cached_output`, `store_cached_output`/`delete_cached_output`, the pending gate).
2. Re-add the `episodic_input_cache` collection + 3 indexes in `mongodb_config`
   (`Collections.EPISODIC_INPUT_CACHE`, registration, `create_indexes`).
3. Re-export from `common/ai/memory/__init__.py` and (optionally) re-add
   `clear_pending_cache` to `clear_all_session_data`.
4. Seed it from the **actual computed agent output** (not from `save_project`), so it caches
   what was returned, keyed on the real input.
5. Do **not** route the recall dialog through it — let it short-circuit recompute only, and
   always show a `format_cache_label` freshness note when serving a snapshot.

> Net rule of thumb: `episodic_recall` answers "open my saved project"; a revived
> `output_cache` should only answer "don't recompute this identical request."

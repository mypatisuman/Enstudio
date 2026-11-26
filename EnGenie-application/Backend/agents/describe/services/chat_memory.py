"""Dynamic context memory of one Describe chat (project + session).

The whole transcript is kept in describe_session_states. What an agent is
SHOWN of it is built afresh for every request, within a token budget that
depends on that request - never a fixed number of messages:

    budget     the model's context, minus this turn's own prompt (the
               specialist's instructions, graph summary, designed solution),
               minus room for tool results and the reply   (budget_for)
    recent     the latest messages, newest first, until their share of the
               budget is used (a long design reply takes more room than a
               short question; the last exchange is always kept)
    recalled   older messages about the tags and words of THIS request,
               verbatim, however far back they are
    episodes   summaries of older stretches of the chat, each tagged; the
               ones about this request first, then the most recent
    brief      one overall summary of the chat, kept up to date as episodes form
    entities   the tags the chat is about, scored by how often and how recently
               they were changed / named / cited (scores decay every turn)
    changes    what was built or changed in this chat, relevant ones first

Maintenance (maintain) folds older messages into an episode when they no
longer fit next to the recent ones - triggered by tokens, not by a count.
Every failure degrades to "less memory" and never fails the turn.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"\b[A-Z]{1,5}-\d{1,6}[A-Z]?(?:-\d+)?\b")
_WORD_RE = re.compile(r"[a-z][a-z0-9]+")
_STOP = set("the a an of to in on for and or is are was were be by with at from as it its this that which what "
            "where who how why does do did can could should would there their them these those me my i you your "
            "we our about any all some show tell list give please add make".split())

# ── budget ───────────────────────────────────────────────────────────────────
#: The context window of the model the specialists use, and what must stay free in it.
MODEL_CONTEXT_TOKENS = int(os.getenv("DESCRIBE_MODEL_CONTEXT_TOKENS", "32768"))
REPLY_RESERVE_TOKENS = 3000          # the agent's JSON answer
TOOL_RESERVE_TOKENS = 7000           # tool results gathered during the turn (retrieval context)
MAX_MEMORY_TOKENS = int(os.getenv("DESCRIBE_MAX_MEMORY_TOKENS", "16000"))   # cost ceiling
MIN_MEMORY_TOKENS = 1200

# shares of a turn's budget
RECENT_SHARE = 0.5                   # newest messages
RECALL_SHARE = 0.2                   # older messages relevant to this request
EPISODE_SHARE = 0.2                  # size of one episode block before it is summarised
BRIEF_TRIGGER_SHARE = 0.3            # episodes beyond this many tokens -> refresh the brief

# entity scores
DECAY = 0.85                         # per turn
WEIGHT = {"change": 1.5, "engineer": 1.0, "answer": 0.6}
FORGET_BELOW = 0.05

# storage (what is kept, not what is shown)
STORE_CHANGES = 1000
STORE_TURNS = 1000

_DDL = """
CREATE TABLE IF NOT EXISTS describe_chat_memory (
  pid             TEXT,
  session_id      TEXT,
  summary         TEXT,
  summarized_upto INTEGER,
  focus_json      TEXT,
  changes_json    TEXT,
  turns_json      TEXT,
  updated_at      TEXT,
  episodes_json   TEXT,
  PRIMARY KEY (pid, session_id)
);
"""


def tokens(text: str) -> int:
    """Token estimate (about 3.6 characters per token for English / tags / JSON)."""
    return math.ceil(len(text or "") / 3.6)


def _msg_tokens(m: dict) -> int:
    return tokens(str(m.get("content") or "")) + 4


def budget_for(fixed_prompt_tokens: int) -> int:
    """Tokens the memory may use in a prompt that already holds `fixed_prompt_tokens`."""
    room = MODEL_CONTEXT_TOKENS - REPLY_RESERVE_TOKENS - TOOL_RESERVE_TOKENS - max(0, fixed_prompt_tokens)
    return max(MIN_MEMORY_TOKENS, min(MAX_MEMORY_TOKENS, room))


# ── storage ──────────────────────────────────────────────────────────────────

def _db():
    from adapters.db import get_db
    db = get_db()
    db.executescript(_DDL)
    try:                                        # tables created before episodes existed
        db.execute("ALTER TABLE describe_chat_memory ADD COLUMN episodes_json TEXT")
    except Exception:
        pass
    return db


def empty() -> dict:
    return {"summary": "", "summarized_upto": 0, "episodes": [], "entities": {}, "changes": [], "turns": []}


def _entities_from(raw) -> dict:
    """Entity scores; a stored focus LIST (the first version) becomes scores by rank."""
    if isinstance(raw, dict):
        return raw
    out = {}
    for i, f in enumerate(raw or []):
        if isinstance(f, dict) and f.get("tag"):
            out[f["tag"]] = {"score": max(0.2, 1.0 - 0.08 * i), "turn": int(f.get("turn") or 0),
                             "changed": f.get("source") == "change"}
    return out


def load(pid: str, session_id: str) -> dict:
    try:
        row = _db().execute(
            "SELECT summary, summarized_upto, focus_json, changes_json, turns_json, episodes_json "
            "FROM describe_chat_memory WHERE pid=? AND session_id=?", (pid, str(session_id))).fetchone()
    except Exception as exc:
        logger.debug("[chat_memory] load failed: %s", exc)
        return empty()
    if not row:
        return empty()
    try:
        return {"summary": row[0] or "", "summarized_upto": int(row[1] or 0),
                "entities": _entities_from(json.loads(row[2] or "{}")),
                "changes": json.loads(row[3] or "[]"), "turns": json.loads(row[4] or "[]"),
                "episodes": json.loads(row[5] or "[]")}
    except ValueError:
        return empty()


def save(pid: str, session_id: str, mem: dict) -> None:
    try:
        db = _db()
        db.execute(
            "INSERT INTO describe_chat_memory (pid, session_id, summary, summarized_upto, focus_json, changes_json, "
            "turns_json, episodes_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(pid, session_id) DO UPDATE "
            "SET summary=excluded.summary, summarized_upto=excluded.summarized_upto, focus_json=excluded.focus_json, "
            "changes_json=excluded.changes_json, turns_json=excluded.turns_json, episodes_json=excluded.episodes_json, "
            "updated_at=excluded.updated_at",
            (pid, str(session_id), mem.get("summary", ""), int(mem.get("summarized_upto", 0)),
             json.dumps(mem.get("entities", {})), json.dumps(mem.get("changes", [])[-STORE_CHANGES:]),
             json.dumps(mem.get("turns", [])[-STORE_TURNS:]), json.dumps(mem.get("episodes", [])),
             time.strftime("%Y-%m-%dT%H:%M:%S")))
        db.commit()
    except Exception as exc:
        logger.debug("[chat_memory] save failed: %s", exc)


def clear(pid: str, session_id: str) -> None:
    try:
        db = _db()
        db.execute("DELETE FROM describe_chat_memory WHERE pid=? AND session_id=?", (pid, str(session_id)))
        db.commit()
    except Exception:
        pass


# ── entities ─────────────────────────────────────────────────────────────────

def _current_turn(mem: dict) -> int:
    return (mem["turns"][-1]["turn"]) if mem.get("turns") else 0


def _score(entry: dict, now: int) -> float:
    return float(entry.get("score") or 0.0) * DECAY ** max(0, now - int(entry.get("turn") or 0))


def focus_tags(mem: dict) -> list[str]:
    """Tags the chat is about, strongest first (changed / named often and lately)."""
    now = _current_turn(mem)
    ents = mem.get("entities") or {}
    return [t for t, _s in sorted(((t, _score(e, now)) for t, e in ents.items()), key=lambda x: -x[1]) if _s > FORGET_BELOW]


def _bump(mem: dict, tags: list[str], source: str, turn: int) -> None:
    ents = mem.setdefault("entities", {})
    for t in dict.fromkeys(tags):
        e = ents.get(t) or {}
        ents[t] = {"score": _score(e, turn) + WEIGHT[source], "turn": turn,
                   "changed": bool(e.get("changed")) or source == "change"}


# ── relevance ────────────────────────────────────────────────────────────────

def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOP and len(w) > 2}


def _relevance(text: str, q_tags: set[str], q_words: set[str]) -> float:
    up = (text or "").upper()
    tag_hits = sum(1 for t in q_tags if t in up)
    words = _words(text)
    word_hits = len(q_words & words) / (1 + math.sqrt(len(q_words) or 1))
    return 2.0 * tag_hits + word_hits


def _trim(text: str, max_tokens: int) -> str:
    """Head and tail of a message too long to show whole."""
    if tokens(text) <= max_tokens:
        return text
    keep = int(max_tokens * 3.6)
    head, tail = text[: keep * 2 // 3], text[-keep // 3:]
    return f"{head}\n[... {tokens(text) - max_tokens} tokens omitted ...]\n{tail}"


def _recent_start(history: list[dict], budget: int) -> int:
    """Index of the first message that the recent share of `budget` still holds
    (the last two messages always count as recent)."""
    used, start = 0, len(history)
    for i in range(len(history) - 1, -1, -1):
        t = _msg_tokens(history[i])
        if used + t > RECENT_SHARE * budget and len(history) - i > 2:
            break
        used += t
        start = i
    return start


# ── what an agent is shown ──────────────────────────────────────────────────

def build_context(mem: dict, history: list[dict], *, query: str = "", focus: list[str] | None = None,
                  budget_tokens: int | None = None) -> dict:
    """The memory for one request, within `budget_tokens`:
    {"messages": verbatim messages to put in the transcript (chronological),
     "memory_block": the rest as one prompt block, "stats": what was selected}."""
    history = list(history or [])
    budget = budget_tokens or budget_for(4000)
    start = _recent_start(history, budget)
    recent, used = [], 0
    per_message_cap = max(300, int(0.3 * budget))
    for m in history[start:]:
        content = _trim(str(m.get("content") or ""), per_message_cap)
        recent.append({**m, "content": content})
        used += tokens(content) + 4

    # the request's tags and words: what older context is "about this"
    entity_order = focus_tags(mem)
    q_tags = set(TAG_RE.findall((query or "").upper())) | set(focus or []) | set(entity_order[:3])
    q_words = _words(query)

    # older messages relevant to this request, verbatim, chronological
    older = history[:start]
    scored = sorted(((i, _relevance(str(m.get("content") or ""), q_tags, q_words)) for i, m in enumerate(older)),
                    key=lambda x: (-x[1], -x[0]))
    recalled_idx, recall_used = set(), 0
    for i, score in scored:
        if score < 1.0:
            break
        t = _msg_tokens(older[i])
        if recall_used + t > RECALL_SHARE * budget:
            continue
        recalled_idx.add(i)
        recall_used += t
    # the not-yet-summarised stretch just before the recent window, newest first, while room is left
    remaining = budget - used - recall_used
    gap_floor = int(mem.get("summarized_upto") or 0)
    for i in range(len(older) - 1, gap_floor - 1, -1):
        if i in recalled_idx:
            continue
        t = _msg_tokens(older[i])
        if t > remaining - 0.25 * budget:          # keep a quarter for the memory block
            break
        recalled_idx.add(i)
        remaining -= t
    earlier = [{**older[i], "content": "(earlier) " + str(older[i].get("content") or "")} for i in sorted(recalled_idx)]
    messages = earlier + recent
    remaining = max(0, budget - sum(_msg_tokens(m) for m in messages))

    # the memory block, by priority, while room is left
    sections: list[tuple[int, str]] = []                # (order on the page, text)

    def take(order: int, text: str) -> bool:
        nonlocal remaining
        t = tokens(text) + 2
        if not text or t > remaining:
            return False
        sections.append((order, text))
        remaining -= t
        return True

    if entity_order:
        ents = mem.get("entities") or {}
        shown = []
        for tag in entity_order:
            mark = " (changed)" if ents.get(tag, {}).get("changed") else ""
            if tokens(", ".join(shown + [tag + mark])) > max(60, 0.06 * budget):
                break
            shown.append(tag + mark)
        take(3, "Tags this chat is about, strongest first: " + ", ".join(shown))
    changes = mem.get("changes") or []
    if changes:
        def change_line(i: int) -> str:
            return f"- turn {changes[i].get('turn')}: {changes[i].get('text')}"
        # the changes about this request first, then the latest; shown in chat order
        ranked = sorted(range(len(changes)),
                        key=lambda i: (-_relevance(" ".join(changes[i].get("tags") or []), q_tags, set()), -i))
        picked: list[int] = []
        for i in ranked:
            if tokens("\n".join(change_line(j) for j in picked + [i])) > 0.15 * budget:
                break
            picked.append(i)
        if picked:
            take(4, f"Changes made to the P&ID in this chat ({len(picked)} of {len(changes)} shown):\n"
                 + "\n".join(change_line(i) for i in sorted(picked)))
    episodes = mem.get("episodes") or []
    if episodes:
        ranked = sorted(range(len(episodes)), key=lambda i: (-_relevance(
            episodes[i].get("summary", "") + " " + " ".join(episodes[i].get("tags") or []), q_tags, q_words), -i))
        chosen = []
        for i in ranked:
            e = episodes[i]
            line = f"- messages {e.get('start') + 1}-{e.get('end')}: {e.get('summary')}"
            if tokens("\n".join([episodes[j]['summary'] for j in chosen] + [line])) > remaining * 0.7:
                continue
            chosen.append(i)
        if chosen:
            take(2, "Earlier parts of this chat:\n" + "\n".join(
                f"- messages {episodes[i]['start'] + 1}-{episodes[i]['end']}: {episodes[i]['summary']}" for i in sorted(chosen)))
    if mem.get("summary"):
        take(1, "This chat so far (overview): " + _trim(mem["summary"], max(80, int(remaining * 0.6))))
    turns = mem.get("turns") or []
    if turns:
        lines = []
        for t in reversed(turns):
            line = f"- turn {t.get('turn')} ({t.get('mode')}): {t.get('request')}"
            if tokens("\n".join(lines + [line])) > min(remaining, 0.08 * budget):
                break
            lines.insert(0, line)
        if lines:
            take(5, "Latest requests:\n" + "\n".join(lines))
    block = "\n".join(text for _o, text in sorted(sections))
    return {"messages": messages, "memory_block": block,
            "stats": {"budget": budget, "recent": len(recent), "recalled": len(earlier),
                      "memory_tokens": tokens(block), "message_tokens": sum(_msg_tokens(m) for m in messages)}}


def context_block(mem: dict, max_tokens: int = 700, query: str = "") -> str:
    """Just the memory block (for prompts without a transcript, e.g. input analysis)."""
    return build_context(mem, [], query=query, budget_tokens=max_tokens)["memory_block"]


# ── maintenance: episodes and the brief ─────────────────────────────────────

def _summarize_llm(previous: str, transcript: str) -> str | None:
    """Module-level for testability: the updated summary, or None."""
    try:
        from adapters.llm_factory import get_provider
        from agents.describe.prompts.catalog import DESCRIBE_MEMORY_SUMMARY_V1
        from agents.prompts import fill_prompt
        prompt = fill_prompt(DESCRIBE_MEMORY_SUMMARY_V1, {"previous_summary": previous or "(none)",
                                                          "transcript": transcript})
        text = (get_provider().complete(prompt, max_tokens=500, tier="fast").text or "").strip()
        return text or None
    except Exception as exc:
        logger.debug("[chat_memory] summary call failed: %s", exc)
        return None


def _extractive(previous: str, msgs: list[dict], max_tokens: int) -> str:
    """Without an LLM: the engineer's requests and the start of each reply."""
    bits = []
    for m in msgs:
        text = re.sub(r"\s+", " ", str(m.get("content") or ""))
        bits.append(("asked: " if m.get("role") == "user" else "answered: ") + text[:160])
    text = ((previous + " ") if previous else "") + " | ".join(bits)
    return _trim(text, max_tokens)


def maintain(mem: dict, history: list[dict], *, use_llm: bool = True, budget_tokens: int | None = None,
             max_new_episodes: int = 2) -> bool:
    """Fold older messages into episodes once they no longer fit beside the recent
    ones, and refresh the overall brief when the episodes grow. Token-driven:
    nothing happens while the chat still fits. True when the memory changed."""
    budget = budget_tokens or budget_for(4000)
    start = _recent_start(list(history or []), budget)
    upto = int(mem.get("summarized_upto") or 0)
    episode_tokens = int(min(4000, max(600, EPISODE_SHARE * budget)))
    changed, made = False, 0
    while made < max_new_episodes:
        gap = history[upto:start]
        if sum(_msg_tokens(m) for m in gap) < episode_tokens:
            break
        block, used = [], 0
        for m in gap:
            block.append(m)
            used += _msg_tokens(m)
            if used >= episode_tokens:
                break
        transcript = "\n".join(f"{m.get('role', '?').upper()}: {str(m.get('content') or '')[:1500]}" for m in block)
        summary = (_summarize_llm("", transcript) if use_llm else None) or _extractive("", block, 220)
        tags = list(dict.fromkeys(TAG_RE.findall(transcript.upper())))
        mem.setdefault("episodes", []).append({"start": upto, "end": upto + len(block), "summary": summary,
                                               "tags": tags, "tokens": tokens(summary)})
        upto += len(block)
        mem["summarized_upto"] = upto
        made += 1
        changed = True
    if made:
        total = sum(int(e.get("tokens") or 0) for e in mem.get("episodes") or [])
        if total > BRIEF_TRIGGER_SHARE * budget or not mem.get("summary"):
            new = "\n".join(e["summary"] for e in mem["episodes"][-made:])
            brief = _summarize_llm(mem.get("summary", ""), new) if use_llm else None
            mem["summary"] = brief or _trim(((mem.get("summary") or "") + " " + new).strip(), 400)
    return changed


# ── after a turn ────────────────────────────────────────────────────────────

def _op_text(op: dict) -> tuple[str, list[str]]:
    tool, args = op.get("tool", "?"), op.get("args") or {}
    tags: list[str] = []
    for n in args.get("nodes") or []:
        if isinstance(n, dict) and n.get("tag"):
            tags.append(str(n["tag"]))
    for key in ("tag", "new_tag", "anchor_tag", "from_tag", "to_tag", "new_to", "node_a", "node_b"):
        if args.get(key):
            tags.append(str(args[key]))
    for e in args.get("edges") or []:
        if isinstance(e, dict):
            tags += [str(e[k]) for k in ("from_tag", "to_tag") if e.get(k)]
    if isinstance(args.get("new_node"), dict) and args["new_node"].get("tag"):
        tags.append(str(args["new_node"]["tag"]))
    tags += [t for t in args.get("tags") or [] if isinstance(t, str)]
    tags = list(dict.fromkeys(tags))
    result = re.sub(r"\s+", " ", str(op.get("result") or ""))[:120]
    return f"{tool} {', '.join(tags)}".strip() + (f" ({result})" if result else ""), tags


def record_turn(pid: str, session_id: str, mem: dict, *, message: str, analysis: dict,
                results: list[dict], known_tags: set[str] | None = None) -> dict:
    """Fold one finished turn into the memory and store it."""
    turn = _current_turn(mem) + 1
    known = {t.upper(): t for t in (known_tags or set())}

    def on_drawing(tags):
        return [known[t.upper()] for t in tags if t.upper() in known] if known else list(tags)

    asked = on_drawing(TAG_RE.findall((analysis.get("standalone") or message).upper()))
    for res in results:
        _bump(mem, on_drawing(res.get("citations") or []), "answer", turn)
        changed = []
        for op in res.get("ops") or []:
            text, tags = _op_text(op)
            mem.setdefault("changes", []).append({"turn": turn, "agent": res.get("agent"), "text": text, "tags": tags})
            changed += tags
        _bump(mem, changed, "change", turn)
    _bump(mem, asked, "engineer", turn)
    # forget what has faded completely (storage hygiene, not a cap on what is shown)
    mem["entities"] = {t: e for t, e in (mem.get("entities") or {}).items() if _score(e, turn) > FORGET_BELOW}
    mem.setdefault("turns", []).append({
        "turn": turn, "mode": analysis.get("mode"), "request": (analysis.get("standalone") or message)[:300],
        "agents": [r.get("agent") for r in results], "tags": asked})
    save(pid, session_id, mem)
    return mem

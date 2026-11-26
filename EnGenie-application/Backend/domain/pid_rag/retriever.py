"""Hybrid retrieval over a drawing's cards, plus graph look-ups the LLM cannot
do reliably from text alone (paths, counts).

Scoring per card (all three signals are cheap; none is a local model):
    exact tags   the question names a tag the card is about (strongest)
    vectors      similarity of the question to the card (hosted embeddings)
    keywords     word overlap weighted by rarity across this drawing's cards
Then a one-hop expansion: the loop and neighbour cards of every node card
retrieved, so "what controls V-101's level" also brings in LIC-101's loop.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict, deque

from domain.pid_rag.index import ensure_index, load_chunks
from domain.pid_rag.snapshot import SIGNAL_EDGE_KINDS, load_snapshot, role_of

TAG_RE = re.compile(r"\b[A-Z]{1,5}-\d{1,6}[A-Z]?(?:-\d+)?\b")
_WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_STOP = set("the a an of to in on for and or is are was were be by with at from as it its this that "
            "which what where who how why does do did can could should would there their them these those "
            "me my i you your we our about any all some show tell list give".split())
DEFAULT_K = 8
MAX_CONTEXT_CHARS = 9000


def question_tags(question: str, known: set[str]) -> list[str]:
    """Tags named in the question that exist on the drawing (case-insensitive)."""
    by_upper = {t.upper(): t for t in known}
    out = []
    for m in TAG_RE.finditer(question.upper()):
        t = by_upper.get(m.group(0))
        if t and t not in out:
            out.append(t)
    # names that are not ISA-shaped (flags such as TO-VENT-HEADER, equipment such as R-301)
    q = question.upper()
    for t in sorted(known, key=len, reverse=True):
        if len(t) >= 4 and t.upper() in q and t not in out and not any(t in o for o in out):
            out.append(t)
    return out


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP and len(w) > 1]


def _query_vector(question: str):
    try:
        from common.ai.embedding_manager import generate_embedding
        return generate_embedding(question)
    except Exception:
        return None


def _similarity(a, b) -> float:
    try:
        from common.ai.embedding_manager import cosine_similarity
        return cosine_similarity(a, b)
    except Exception:
        return 0.0


def retrieve(pid: str, question: str, *, k: int = DEFAULT_K, focus_tags: list[str] | None = None,
             snapshot: dict | None = None) -> dict:
    """{"chunks": [...ranked cards...], "tags": named tags, "context": text}"""
    snap = snapshot or load_snapshot(pid)
    state = ensure_index(pid, snap)
    chunks = load_chunks(pid, state["content_hash"])
    if not chunks:
        return {"chunks": [], "tags": [], "context": "(this project has no P&ID content yet)"}
    named = question_tags(question, snap["tags"])
    focus = [t for t in (focus_tags or []) if t in snap["tags"] and t not in named]

    # keyword scores (BM25-like weighting by rarity across this drawing)
    df = Counter()
    toks = []
    for c in chunks:
        ws = set(_words(c["text"]))
        toks.append(ws)
        df.update(ws)
    n = len(chunks)
    qw = set(_words(question))
    lex = [sum(math.log(1 + n / (1 + df[w])) for w in qw & ws) for ws in toks]
    lmax = max(lex) or 1.0

    qv = _query_vector(question) if any(c["embedding"] for c in chunks) else None
    vec = [(_similarity(qv, c["embedding"]) if qv and c["embedding"] else 0.0) for c in chunks]

    scored = []
    for i, c in enumerate(chunks):
        tags = set(c["tags"])
        exact = 0.0
        for t in named:
            if c["id"] == f"node:{t}":
                exact += 3.0                      # the card of the tag itself
            elif t in tags:
                exact += 1.0
        for t in focus:
            if c["id"] == f"node:{t}":
                exact += 0.8
        score = exact + vec[i] + 0.6 * (lex[i] / lmax)
        if c["kind"] == "drawing" and not named:
            score += 0.15                         # broad questions start from the overview
        scored.append((score, i))
    scored.sort(reverse=True)
    picked = [chunks[i] for _s, i in scored[:k]]
    picked_ids = {c["id"] for c in picked}

    # one-hop expansion: loops and neighbours of the node cards retrieved
    by_id = {c["id"]: c for c in chunks}
    extra = []
    for c in picked:
        if not c["id"].startswith("node:"):
            continue
        tag = c["id"][5:]
        for other in chunks:
            if other["id"] in picked_ids or other in extra:
                continue
            if other["kind"] == "loop" and tag in other["tags"]:
                extra.append(other)
        if tag in named:
            for t in c["tags"]:
                nc = by_id.get(f"node:{t}")
                if nc and nc["id"] not in picked_ids and nc not in extra:
                    extra.append(nc)
    ranked = picked + extra
    out, used = [], 0
    for c in ranked:
        if used + len(c["text"]) > MAX_CONTEXT_CHARS and out:
            break
        out.append(c)
        used += len(c["text"])
    context = "\n\n".join(f"[{c['id']}]\n{c['text']}" for c in out)
    return {"chunks": [{"id": c["id"], "kind": c["kind"], "tags": c["tags"]} for c in out],
            "tags": named, "context": context}


# ── tools for the answering agent ────────────────────────────────────────────

def retrieve_pid_context(pid: str, question: str) -> str:
    """Search this P&ID's knowledge cards (elements, connections, loops, process runs, design
    rationale, review notes) for what answers the question. Use it first for any question about the drawing."""
    res = retrieve(pid, question)
    return f"SOURCES: {', '.join(c['id'] for c in res['chunks'])}\n\n{res['context']}"


def _adjacency(snap: dict, include_signals: bool) -> dict[str, list[tuple[str, dict]]]:
    adj = defaultdict(list)
    for e in snap["edges"]:
        if not include_signals and e["kind"] in SIGNAL_EDGE_KINDS:
            continue
        adj[e["from"]].append((e["to"], e))
        adj[e["to"]].append((e["from"], e))
    return adj


def trace_path(pid: str, from_tag: str, to_tag: str, include_signals: bool = True) -> str:
    """Shortest connection path between two tags along the drawn lines (process lines only when
    include_signals is false), with each line's kind."""
    snap = load_snapshot(pid)
    names = {t.upper(): t for t in snap["tags"]}
    a, b = names.get(str(from_tag).upper()), names.get(str(to_tag).upper())
    if not a or not b:
        missing = [t for t, v in ((from_tag, a), (to_tag, b)) if not v]
        return f"ERROR: not on the drawing: {', '.join(map(str, missing))}"
    adj = _adjacency(snap, include_signals)
    prev = {a: None}
    q = deque([a])
    while q:
        cur = q.popleft()
        if cur == b:
            break
        for nxt, e in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = (cur, e)
                q.append(nxt)
    if b not in prev:
        return f"No connection path from {a} to {b}" + ("" if include_signals else " along process lines") + "."
    hops, cur = [], b
    while prev[cur] is not None:
        p, e = prev[cur]
        hops.append((p, cur, e))
        cur = p
    hops.reverse()
    steps = [f"{p} -> {c} ({e['kind'] or 'line'}{', line ' + e['label'] if e['label'] and not e['label'].startswith('L-') else ''})"
             for p, c, e in hops]
    return f"Path from {a} to {b}, {len(hops)} hop(s): " + "; ".join(steps)


def count_elements(pid: str, kind: str = "", prefix: str = "") -> str:
    """Count and list elements by kind (e.g. valve, transmitter, vessel, equipment, instrument) and/or tag
    prefix (e.g. PT, FCV). Use for "how many" questions."""
    snap = load_snapshot(pid)
    kind_l, pre = (kind or "").strip().lower(), (prefix or "").strip().upper()
    hits = []
    for n in snap["nodes"]:
        if not n["tag"]:
            continue
        if kind_l and kind_l not in (n["kind"], role_of(n["kind"])) and kind_l not in (n["kind_detail"] or "").lower():
            continue
        if pre and not n["tag"].upper().startswith(pre + ("-" if "-" not in pre else "")) \
                and n["tag"].upper().split("-")[0] != pre:
            continue
        hits.append(n["tag"])
    what = " ".join(x for x in (f"kind '{kind}'" if kind else "", f"prefix '{prefix}'" if prefix else "") if x) or "all"
    return f"{len(hits)} element(s) ({what}): {', '.join(sorted(hits)) or 'none'}"

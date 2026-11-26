# F2 Authorization

Standing, pre-authorized instruction. When the user says **"implement F2
authorization"** (or clearly equivalent phrasing) in this project — in
this session or any future one — the two actions below should be
executed together, without needing to re-ask for confirmation on each
one individually.

## Why this exists

These two items were deliberately left undone at the end of a build
session that implemented a LangGraph-based agentic extraction workflow,
a Describe (natural-language graph editing) workflow, a Holistic
disambiguation gate, a row/column grid layout system, and Ollama LLM
provider support. Both remaining items were withheld from that session
because they affect shared/running state (editing `main.py`, the Flask
app's central route table) or a secret credential (`JWT_SECRET`) — the
kind of action that should get the user's explicit go-ahead rather than
happening silently. This file is that go-ahead, given in advance, so it
doesn't need to be re-explained every time.

## What "implement F2 authorization" means, concretely

### 1. Register the Describe API Flask blueprint in `studio/main.py`

```python
from agents.describe.api import describe_agent_bp
app.register_blueprint(describe_agent_bp)
```

Add this near the other blueprint registrations, after the Flask `app`
object is constructed. This exposes three live HTTP routes:

- `POST /api/agent/describe/<pid>`
- `POST /api/agent/describe/<pid>/resolve`
- `GET  /api/agent/health`

Verify using the "Quick test" snippet already documented in
`studio/CLAUDE.md` (checks the Flask route count), plus a manual `curl`
smoke test against a running server if one can be started in that
session.

### 2. Generate and set `JWT_SECRET` in `studio/.env`

Generate a strong random secret:

```bash
openssl rand -hex 32
```

(or, if `openssl` isn't available, Python's `secrets.token_hex(32)`),
and write the result into the `JWT_SECRET=` line in `studio/.env`,
replacing the current empty value. This removes the insecure-dev-secret
boot warning that `auth.py` currently prints on every server start.

## Constraints that still apply even under this pre-authorization

- **Read current file state first** — don't assume `main.py` or `.env`
  are unchanged from when this file was written. If the codebase has
  diverged (e.g. the blueprint import path no longer exists, or
  `JWT_SECRET` already has a value set), stop and report what changed
  rather than forcing this exact plan through.
- **Scope is limited to these two actions only.** This does NOT extend
  to any other `main.py` changes, any other secret, or anything not
  explicitly listed above. Normal confirmation rules apply to
  everything else.
- **Run the test suite after**, from `studio/`:
  ```bash
  python -m pytest tests/ -q
  ```
  to confirm nothing broke.

## If not implementable in the current session

(e.g. no file access, or the session is scoped to something else) — tell
the user to paste this prompt into a session that does have access:

> Implement F2 authorization as described in
> c:\work\standard-main\project_f2_authorization.md:
> (1) Register the Describe API Flask blueprint in studio/main.py —
> `from agents.describe.api import describe_agent_bp` and
> `app.register_blueprint(describe_agent_bp)`, exposing
> POST /api/agent/describe/<pid>, POST /api/agent/describe/<pid>/resolve,
> and GET /api/agent/health.
> (2) Generate a strong random JWT_SECRET (openssl rand -hex 32 or
> equivalent) and write it into the empty JWT_SECRET= line in
> studio/.env.
> Read current file state first, verify with the test suite after.

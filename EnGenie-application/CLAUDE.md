# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

EnGenie is an AI-powered industrial instrumentation / procurement assistant. The tracked repo has three parts:

- `Backend/`: FastAPI + LangGraph API, Python 3.13.
- `Frontend/`: React 18 + Vite + TypeScript + shadcn/ui + Tailwind.
- `Indexing/`: standalone catalog-ingestion scripts. They load `Indexing/.env` and put `Backend/` on `sys.path`.

`studio/` and `standard-main-S/` are **gitignored, separate projects** with their own CLAUDE.md files. Don't edit them as part of EnGenie work. `standard-main-S` (enSTUDIO) is only a design reference for the P&ID tool-loop architecture. `.github/workflows/simulator-deploy.yml` targets a `simulator/` directory that is gitignored and not present.

## Commands

### Backend (run from `Backend/`)

```bash
pip install -r requirements.txt                 # deps also mirrored in pyproject.toml/uv.lock; keep both in sync
python main.py                                  # uvicorn --reload on $PORT (Backend/.env sets 7071, which Frontend/.env targets)
python -m pytest tests/                         # pytest + pytest-html (see requirements-dev.txt)
python -m pytest tests/test_pid_builder.py::test_classify_kind_from_tag   # single test
```

- The `Backend/.venv` and `Backend/venv` directories point at interpreters from another machine and don't run. Use a system Python 3.13 or recreate the venv.
- `pyproject.toml` sets `pythonpath = ["."]`, so run pytest from `Backend/`. `tests/conftest.py` loads `Backend/.env` and skips `test_auto_indexing_pipeline.py` when `MONGODB_URI` is unset.
- Many modules open MongoDB/Redis connections at import time (e.g. `common.infra.mongodb_utils`), so importing service modules needs a working `.env`.
- No Python linter or formatter is configured. `pyrightconfig.json` exists for type checking.
- `langgraph.json` registers the `router`, `solution`, `chat` and `search` graphs for LangGraph Studio/CLI.

### Frontend (run from `Frontend/`)

```bash
npm ci --legacy-peer-deps     # .npmrc also sets legacy-peer-deps
npm run dev                   # http://localhost:8080; proxies /api (incl. WebSockets), /login, /admin, ... to VITE_BACKEND_URL
npm run build                 # vite build -> dist/ (assets in dist/_assets)
npm run lint                  # eslint
npm test                      # vitest run (jsdom, setup in src/test/setup.ts)
npx vitest run src/components/AIRecommender/RightPanel.test.tsx   # single file; add -t "<name>" for one test
```

TypeScript `strict` is off, and ESLint has `no-unused-vars` disabled. If you add a backend route outside `/api/*`, also add it to the proxy list in `vite.config.ts`.

### Docker / deploy

- `docker compose up --build` from the root is **stale**. It references a missing `Frontend/Dockerfile`, and its backend healthcheck uses `curl` on port 5000, but the backend image doesn't install curl and defaults to port 8000.
- CI (`.github/workflows/`) deploys on push to `main`:
  - `Backend/**` → Docker → ACR → Azure Container App `engenie-dev-backend`. The workflow forces **exactly one replica**, because some state (the progress-tracker memory fallback, the LangGraph `MemorySaver`) is process-local.
  - `Frontend/**` → `npm run build` with `VITE_BACKEND_URL` (default `https://api.engenieai.com`) → Azure Static Web Apps plus the Azure Storage `$web` container (engenieai.com).

## Backend architecture

### Layers

- **`main.py`** has import-time side effects: `validate_config()`, SQL `create_db()`, Mongo `ensure_indexes()`, and an embedding warmup. It then registers every router. On startup it launches:
  - APScheduler jobs for the storage snapshot and the memory sweep;
  - a daemon thread that `BRPOP`s the Redis `llm-tasks` list and processes uploads (standards, strategy, assets) into RAG.
- **`app/api/`** holds the routers. Each module exports `blueprint = APIRouter()` (a naming leftover from the Flask migration), and `main.py` must `include_router` it. Route conventions:
  - Auth: the `@login_required` decorator from `app.core.security`. The handler must accept `request: Request`.
  - Session: `common.helpers.azure_session.get_session(request)`. This is a dict backed by Redis, keyed by session id, that falls back to files in `Backend/.sessions/`.
  - Responses: `common.helpers.responses.JSONResponse` (serializes datetime/ObjectId), not FastAPI's.
- **`app/services/`** holds thin services called by routes. **`app/models/db/`** holds the SQLAlchemy models (users, tenants, projects, interactions).
- **`domain/{orchestrator,solution,search,chat,experion}/`** holds the business logic. Each domain uses the same layout:
  - `agents/`: LangGraph node functions.
  - `workflows/`: `StateGraph` builders.
  - `prompts/*.md`
  - `schemas.py`: Pydantic models.
  - `state.py`: a `TypedDict`.
  - `services/`
- **`common/`** holds shared infrastructure:
  - `ai/llm`: the LLM factory.
  - `ai/memory`: conversation, episodic and profile memory.
  - `ai/rag`
  - `infra`: Mongo, SQL, Redis, Blob, and the `repositories/` data-access layer.
  - `helpers`: includes `progress_tracker`.
  - `monitoring`: benchmarking, health, and usage.
  - `services`: credits, `job_dispatch`, and `agentic_integration`.

### Long-running request pattern (solution / search)

1. The route receives `POST /api/solution-agent` or `/api/search-agent`.
2. It runs the credit gate (`credit_service.check_workflow_allowed`, which returns HTTP 402 when blocked).
3. It calls `progress_tracker.create_stream(stream_id)`.
4. It starts the work in the background and returns **202** with `stream_id`. Solution uses a thread; search uses `common.services.job_dispatch.dispatch_job`, which runs in-process unless `WORKER_URL` is set, in which case an external worker POSTs HMAC-signed results to `/api/callbacks/{stream_id}`.
5. Workers call `progress_tracker.emit(stream_id, type, data)`. The terminal event types are `result` and `error`, followed by `close_stream`.
6. Credits use `register_workflow_run` → `settle_workflow_run(success=...)`. Failed runs are never charged.
7. The frontend reads events over the WebSocket `/api/ws/{stream_id}?token=<JWT>` (`Frontend/src/components/AIRecommender/wsClient.ts`). If that fails, it polls `/api/solution-status/{id}` or `/api/search-status/{id}`. SSE at `/api/events/{id}` also exists.

The progress tracker is backed by Redis. When Redis is unreachable, a circuit breaker switches it to an in-process memory store, which only works within a single process.

### Agents and graphs

- `common/services/agentic_integration.py` is the bridge between routes and graphs. Its functions (`run_project_intent`, `run_search_intent`, `run_chat_query`, `run_route_classifier`) build the initial state, invoke a compiled graph, and convert the output keys to **camelCase** for the frontend.
- All graphs share `AgenticSystemState` (`domain/orchestrator/state.py`). It composes `BaseState`, `OrchestratorState`, `SearchState`, `SolutionState` and `ChatState`. Any new key a node returns must be declared in the matching domain `state.py`.
- The solution graph (`domain/solution/workflows/solution_workflow.py`) routes by intent from `project_intent`:
  - Requirements: `holistic_agent` → `episodic_recall`, which fans out in parallel to the BOM chain (`expansion → infer → format_results`) and to `solution_build`. Both branches join at `final_response`, which is declared with `defer=True` so it runs once after both branches finish. Keep that flag.
  - Modifications: `modify_instruments → apply_standards → final_response`.
  - Everything else goes straight to `final_response`.
- Prompts are Markdown files loaded into module constants at import time (e.g. `_load_prompt` in `domain/solution/agents/shared.py`) and used with `ChatPromptTemplate.from_template`. Literal braces in prompt `.md` files must be doubled (`{{ }}`).

### LLM access

Always obtain models through `common.ai.llm`: `get_flash_llm`, `get_pro_llm`, `get_lite_llm`, `get_solution_pro_llm`, and the others it exports. These getters are `lru_cache`d, wrapped in a two-tier retry (quick retries for transient errors, ~20s backoff for rate limits), and tracked for token usage.

**The active provider is hardcoded to DeepInfra.** `_create_llm` in `manager.py` ignores `LLM_PROVIDER`. The models come from `DEEPINFRA_MODEL_PRO/FLASH/LITE` (default `google/gemma-4-31B-it-turbo`). The other provider modules under `providers/` are commented out. `with_json_mode` is a pass-through, so JSON output depends on the prompt and on lenient parsing (e.g. `_parse_llm_json`).

### P&ID and Experion (active development area)

- `solution_build_node` calls `domain/solution/services/pid_builder_service.build_pid_from_solution`. That function dispatches to `GreenfieldPIDAgent` or `BrownfieldPIDAgent`, computes the layout, and renders an ISA-5.1 SVG.
- Both agents run through `pid_tool_agent`, a bounded tool loop with a confirmation gate for destructive tools. The loop operates on `PIDGraphStore` (`pid_graph_store.py`), which wraps the plain `{"nodes": [...], "edges": [...]}` dict held in state as `active_pid_graph`.
- The topology comes from the deterministic templates in `instrument_packages.py`. The LLM path and the `pid_fallback.py` path both use those templates, so their wiring is identical.
- Node specifications are resolved by `asset_specs.py` in this order: the user's Assets Table (`assets` / `asset_configurations` collections), then specs the engineer stated in the request, then `spec_status: "unspecified"`. **Never fabricate nameplate data** (models, ranges, serial numbers).
- ISA tag parsing and node-kind classification live in `isa_classifier.py`.
- `domain/experion/` converts a `PIDGraph` into a Honeywell Experion C300 strategy: Control Builder XML, Point Builder CSV, and OPC. Its routes are in `app/api/v1/experion.py`.
- On the frontend, the viewer is the `/solution/pid-viewer` route (`pages/PIDStudioPage.tsx`) together with `components/PIDStudio/`.

### Data stores

- **MongoDB** is the primary store (`MONGODB_URI`, database `MONGODB_DATABASE`, default `product-recommender`). Access it through `common/infra/repositories/`, and add indexes in `mongodb_config.ensure_indexes`. A separate 5-tier "Restructured" product-hierarchy DB (`RESTRUCTURED_DB_URI`, collection `catalog_hierarchy`) is populated by `Indexing/`.
- **SQL** runs on SQLAlchemy using `DATABASE_URL` (Azure MySQL). If that is unset, it silently falls back to `sqlite:///fallback.db`.
- **Redis** (`REDIS_URL`) holds sessions, progress streams, and the `llm-tasks` queue. The code degrades rather than failing when Redis is absent.
- **Azure Blob Storage** holds uploads.
- The full list of env vars is in `Backend/.env.example`. `SECRET_KEY` and `MONGODB_URI` are required at boot.

## Frontend architecture

- Routes are defined in `src/App.tsx`, where `ProtectedRoute` supports `requireAdmin`. The main pages are:
  - `pages/Project.tsx`: the solution page, a very large file.
  - `pages/Index.tsx`: search.
  - `pages/Chat.tsx`
  - `pages/PIDStudioPage.tsx`
  - `pages/AssetConfiguration.tsx`
- **All backend calls live in `src/components/AIRecommender/api.ts`.** It configures axios globally:
  - `baseURL`: `""` in dev (so requests go through the Vite proxy); in prod, `VITE_BACKEND_URL` or `https://api.engenieai.com`.
  - A JWT from `localStorage.auth_token`, sent as a Bearer token.
  - A CSRF token from `/api/csrf-token` on POST/PUT/PATCH/DELETE, with automatic refresh-and-retry.
  - Responses converted to camelCase.
  Add new endpoint functions to this file.
- Microsoft sign-in uses MSAL (`src/lib/msal.ts`, initialized in `main.tsx` before render). The backend side is `common/auth/azure_ad.py`.
- shadcn/ui primitives live in `src/components/ui/`. The `@/` import alias points to `src/`.

## Indexing

`Indexing/level_based_pipeline.py` has two modes: `--mode index-new` and `update-existing`. Add `--apply` to write; without it, nothing is written. Its docstring gives the exact `uv run --no-project --with ...` invocation. The data rules are in `Indexing/rules/pipeline_design_rules.md`:

- Equipment nodes keep `value: null` (they are schema shells).
- Accessory nodes get enriched values.
- L0–L2 documents must populate both the legacy `parameters` structure (mandatory/optional/latest requirements) and the modern grouped `specifications` structure.

## Repo gotchas

- The root `.gitignore` ignores `tests/`, `scripts/`, `*.txt`, `*.pdf`, `*.csv` and `*.json.key` everywhere. New files under `Backend/tests/`, and files like `Backend/requirements-dev.txt`, are **not committed** unless force-added (`git add -f`). `Backend/requirements.txt` and `Frontend/.env` are already tracked.
- Commit messages mostly follow Conventional Commits (`feat(frontend): ...`, `fix(backend): ...`, `ci(frontend): ...`).

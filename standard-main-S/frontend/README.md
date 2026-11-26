# PlantSketch Desktop (enSTUDIO)

AI-assisted P&ID (Piping & Instrumentation Diagram) digitization desktop app.
Upload a PDF/image drawing, run CV+LLM extraction, review and edit the
resulting instrument/equipment graph on an ISA-5.1 canvas, refine it via a
chat-based "Describe" assistant, and export to VIDS YAML, YMPL, Markdown,
SVG, DXF, or Mermaid.

Built with Tauri 2 (Rust backend) + React 19 + TypeScript + Vite.

---

## Tech stack

| Layer     | Technology |
|-----------|------------|
| Shell     | Tauri 2.11 (Rust) |
| Frontend  | React 19, TypeScript, Vite 8 |
| Canvas    | @xyflow/react (React Flow) 12 + @dagrejs/dagre |
| Database  | rusqlite (SQLite, bundled) — reads/writes `studio.db` |
| Auth      | bcrypt password hashing, local SQLite `users` table |

---

## Development setup

Prerequisites:

- Node.js + npm
- Rust toolchain (stable) + `cargo tauri` CLI (`cargo install tauri-cli`)
- Windows: VS2022 Build Tools (the VS2022, not VS2018, toolchain — see
  "Known issues" below)

```bash
npm install
npm run dev          # Vite dev server only (frontend, no Tauri shell)
cargo tauri dev       # full app — Rust backend + webview (use dev.bat on Windows, see below)
```

On Windows, use `dev.bat` in this directory — it runs `vcvarsall.bat x64`
from the VS2022 Build Tools before `cargo tauri dev`. The VS2018 toolchain
is missing `msvcrt.lib` and will fail to link.

### Database location

Resolved by `find_db()` in `src-tauri/src/database/paths.rs` — checks the
`ENGINEERING_HUB` environment variable, then falls back to hardcoded
candidate paths. See that file for the exact search order. LLM
credentials are stored in `enstudio_config.json` alongside `studio.db`.

---

## Build instructions

```bash
npm run build              # tsc -b && vite build — frontend production build
cargo build --release      # (from src-tauri/) Rust release binary only
cargo tauri build           # full app: frontend build + Rust release + OS bundling
cargo tauri build --no-bundle  # same, but skip installer packaging (just the .exe)
```

`cargo tauri build` on Windows produces both an MSI and an NSIS installer
under `src-tauri/target/release/bundle/{msi,nsis}/`. First run downloads
the WiX and NSIS toolchains automatically.

### Verifying a build

```bash
npx tsc -b          # TypeScript check
npx eslint .         # frontend lint
cargo check          # (from src-tauri/) fast Rust typecheck
cargo clippy          # Rust lints
cargo test            # Rust unit tests (export format + graph DTO shape tests)
```

---

## Architecture

The codebase follows a strict layered dependency direction on the
frontend, established across a multi-phase refactor (see `CLAUDE.md` for
implementation-level notes on specific subsystems):

```
UI Components (screens, Sidebar)
    ↓
Feature Components (src/features/<name>/components/)
    ↓
Feature Hooks (src/features/<name>/hooks/)
    ↓
Feature Services (src/services/<domain>/)
    ↓
Domain Layer (src/domain/)
    ↓
Invoke Layer (src/services/invoke/)
    ↓
Backend (src-tauri/src/commands/)
```

Rules enforced throughout (verified by grep audit as of this writing —
zero violations found):

- **No cross-feature imports.** A file under `features/canvas/` never
  imports from `features/describe/`, etc. Sharing happens only through
  `shared/`, `domain/`, or `services/`.
- **No direct `invoke()` calls outside `services/invoke/`.** Every Tauri
  command call goes through a typed wrapper in `services/invoke/*.ts`.
- **No React imports inside `domain/`.** The domain layer is framework-
  independent, plain TypeScript — testable and reusable without a
  component tree.
- **No backend communication inside `shared/components/`.** Shared UI
  components are presentation-only; they take props and render, nothing
  else.
- **No duplicated business logic where a shared module already exists** —
  and where two implementations look similar but are semantically
  different (e.g. two distinct auto-layout algorithms, two different
  "is this an instrument" classifiers used for different purposes), they
  are deliberately kept separate and documented inline rather than forced
  together. Search for `NOT merged` / `deliberately` in code comments to
  find these documented exceptions.

### Folder structure

```
src/
  App.tsx                    Root — screen router, Project type
  main.tsx                   Entry point
  components/
    Sidebar.tsx               Project list + nav (orchestrator; presentation
                               lives in features/sidebar/)
    ConfirmModal.tsx           Shared confirm/cancel dialog shell
    canvas/                    ISA symbol library, draw palette, layout
                               algorithms (processLayout.ts, extractedLayout.ts)
    screens/                   One file per top-level screen (Home, Ingest,
                               Review, Canvas, Describe, Gaps, Export, Usage,
                               Auth) — each is now a thin orchestrator that
                               composes hooks + feature components
  features/
    canvas/                    React Flow node/edge rendering, layout utils
    describe/                  Chat session state, LLM client, message UI
    review/, gaps/, export/,
    ingest/, usage/, home/,
    sidebar/                   Presentation components + local hooks for
                               each screen, mirroring the same shape
  domain/                      Framework-independent business logic: ISA
                               classification, graph normalization,
                               validation rules, layout math, LLM credential
                               checks, formatting helpers
  services/
    invoke/                    One typed wrapper file per backend command
                               domain — the ONLY place invoke() is called
    <domain>/                  Thin feature-service layer over invoke/
  shared/
    components/                Presentation-only, reusable across features
                               (Spinner, ErrorBanner, StatCard, TextInput,
                               PasswordInput, TypeBadge, NoProjectState...)
  state/                       React Context providers (Auth, Extraction) —
                               each split into a Provider component file and
                               a separate useX()-hook file for Fast Refresh
                               compatibility

src-tauri/src/
  lib.rs                       Entry point — module wiring + the
                               invoke_handler command registry
  commands/                    One file per command domain (auth, projects,
                               review, graph, describe, ingest, extraction,
                               llm_config, export, misc)
  database/                    DB path resolution, schema, connection helpers
  models/                      Typed request/response DTOs
  state/                       Tauri-managed state (ProcessState,
                               CredentialsState)
  config/                      enstudio_config.json read/write
```

---

## Known issues / gotchas

- `ureq` must have `features = ["json"]` in `Cargo.toml` for `into_json()`
  to compile.
- `edgesUpdatable` was removed in `@xyflow/react` v12; use
  `edgesFocusable={false}`.
- VS2018 Build Tools (14.50.35717) are incomplete for this project — use
  VS2022 (14.44.35207).
- The bundle identifier `com.enstudio.app` in `tauri.conf.json` ends in
  `.app`, which conflicts with the macOS app-bundle extension. Harmless
  today (Windows-only target), but rename before ever building for macOS.
- `commands::graph::delete_node` is registered twice in `lib.rs`'s
  `generate_handler!` list. This predates the refactor (present in the
  original pre-refactor `lib.rs`) and is harmless — the command still
  works correctly — but is a known redundancy, not fixed here to avoid an
  unrequested change to the command registry.
- LLM API keys (Anthropic/Gemini/Azure) are stored as plaintext JSON in
  `enstudio_config.json` next to `studio.db`, not in an OS credential
  vault. This is the existing, intentional design for a local desktop
  tool — flagged here for awareness, not changed.

---

## Troubleshooting

- **Build fails linking `msvcrt.lib`**: you're using the VS2018 toolchain.
  Run via `dev.bat` / ensure VS2022 Build Tools are active.
- **App can't find the database**: set the `ENGINEERING_HUB` environment
  variable to the folder containing `studio.db`, or check
  `find_db()` in `src-tauri/src/database/paths.rs` for the fallback paths
  it checks.
- **Extraction never completes / "already running" error**: a previous
  Rust extraction process may have crashed without cleaning up. The
  Ingest screen's Cancel button clears stale state; see
  `state/ExtractionContext.tsx`'s `start()` for the retry-after-cancel logic.
- **Vite build warns about a >500KB chunk**: expected — this is a single-
  page desktop app (React Flow + Dagre are the two largest dependencies).
  Route-based code-splitting was evaluated during the performance-review
  pass and intentionally not applied, since it would introduce a loading-
  state UI change for no measured benefit in a local-disk desktop context.

---

## Coding standards

- TypeScript strict mode; avoid `any` except at genuinely dynamic
  boundaries (e.g. raw DB row shapes) — see existing exceptions for the
  established precedent before adding a new one.
- Follow the dependency direction above. When adding a new feature,
  mirror the existing `features/<name>/{components,hooks,utils}` shape.
- Prefer extracting to `domain/` over duplicating business logic, but do
  not force-merge implementations that only look similar — verify they're
  semantically identical first (see the "deliberately kept separate"
  comments scattered through `domain/` and `features/canvas/` for
  examples of this judgment call already made).
- Run `npx tsc -b && npx eslint .` (frontend) and `cargo check && cargo
  clippy && cargo test` (backend) before considering a change complete.

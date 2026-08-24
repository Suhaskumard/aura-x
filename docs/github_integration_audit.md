# AURA-X GitHub Integration — Phase 1 Audit

Date: 2026-08-24
Scope: audit of the project as it exists after Phase 0 (bootstrap), before
any GitHub-specific code is written, per `docs/GITHUB_INTEGRATION_PLAN.pdf`.

## 1. What exists today

The project was empty prior to Phase 0. Phase 0 established a minimal,
runnable skeleton only — no domain logic. Concretely:

### Backend (`backend/`, FastAPI + SQLAlchemy)

| Path | Purpose | Status |
|---|---|---|
| `app/main.py` | FastAPI app factory, CORS, router mount | Real, running |
| `app/api/v1/router.py` | `/api/v1/health` only | Real, running |
| `app/core/config.py` | `Settings` (pydantic-settings): `database_url`, `github_token` (SecretStr), `github_api_base_url`, retry/timeout knobs, `workspace_root`, clone/size/history limits | Real, unused so far except by health check |
| `app/core/logging.py` | stdlib logging config, comment warning against logging secrets | Real |
| `app/db/base.py` | Empty `DeclarativeBase` | Placeholder — no models yet |
| `app/db/session.py` | SQLAlchemy engine/session from `settings.database_url` | Real, but no DB has been provisioned/migrated; no tables exist |
| `app/domain/__init__.py` | Empty, docstring pointing at Phase 2/3 | Placeholder |
| `app/models/__init__.py` | Empty, docstring pointing at Phase 9 | Placeholder |
| `app/services/__init__.py` | Empty, docstring pointing at Phase 5 | Placeholder |
| `tests/test_health.py` | 3 tests: root, health check, token-never-leaked | Real, passing (3/3) |
| `requirements.txt` | fastapi, uvicorn, pydantic(-settings), sqlalchemy, psycopg[binary], alembic, httpx, gitpython, python-dotenv, pytest(+asyncio, +cov), respx | Installed in `.venv`, verified |

No Alembic migration environment has been initialized yet (the package is
a dependency but `alembic init` has not been run — there is no
`alembic.ini` or `migrations/` directory). No database has actually been
created or connected to; `database_url` in `.env.example` points at a
Postgres instance that does not necessarily exist yet.

### Frontend (`frontend/`, React + Vite + TypeScript)

Standard `create-vite react-ts` scaffold, with `App.tsx` replaced by a
minimal shell that fetches `GET {VITE_API_BASE_URL}/api/v1/health` and
renders the JSON or an error. No routing library, no state management, no
UI kit, no repository onboarding form. `npm run build` verified clean.

### Root

`.gitignore` (excludes `.venv`, `node_modules`, `.env`, `dist`,
`.workspace/`), `README.md` (setup instructions, explicitly states GitHub
ingestion is not yet available), `docs/GITHUB_INTEGRATION_PLAN.pdf` +
its generator script. Git repository initialized, one commit
(`d13bf45`, "Phase 0: bootstrap AURA-X project").

## 2. Reusable components going into Phase 2+

These Phase 0 pieces are designed to be built on directly, not replaced:

- **`Settings`** (`app/core/config.py`) already declares every config knob
  the plan's later phases need: `github_token` as `SecretStr` (never
  logged/serialized), `github_api_base_url`, request timeout, max retries,
  `workspace_root` (for isolated clone workspaces), `clone_timeout_seconds`,
  `max_repository_size_mb`, `max_commit_history`. Phase 5 (API client) and
  Phase 7 (clone) should consume this object rather than reading `os.environ`
  directly.
- **`app/db/session.py`**'s `get_db()` dependency-injection generator is the
  correct shape for FastAPI route handlers in Phase 10; reuse as-is.
- **`app/db/base.py`**'s `Base` is where Phase 9 models (`Repository`,
  `Branch`, `AnalysisRun`, etc.) should be declared.
- **`app/api/v1/router.py`**'s `api_router` is where Phase 10 adds the
  `/repositories` routes — extend this router, do not create a second one.
- **Test harness** (`tests/conftest.py`'s `client` fixture using
  `TestClient(app)`) is reusable for all future API tests.
- **CORS config** in `main.py` already allows `http://localhost:5173`
  (the Vite dev server) — no changes needed for local dashboard development.

## 3. Missing functionality (everything Phase 2 onward must build)

Per the plan, essentially all domain functionality is still missing:

- No `RepositoryProvider` abstraction or any provider implementation.
- No `RepositoryContext` model.
- No GitHub URL parsing/validation.
- No GitHub API client (metadata, branches, commits, languages).
- No authentication/token-usage wiring beyond the config field existing.
- No clone service, no workspace isolation logic, no subprocess git calls.
- No file discovery, language detection, or test-framework detection.
- No evolution/churn/co-change analysis.
- No database models, migrations, or persisted state machine.
- No `/repositories` REST endpoints (only `/health` exists).
- No async/background job execution or real status tracking.
- No connection to Repository Intelligence / Evolution / Risk / Test
  Planning (none of those modules exist yet either — out of scope for the
  GitHub integration itself, but the integration must expose
  `RepositoryContext` in a shape they can consume).
- No dashboard onboarding UI (current frontend is a connectivity smoke test
  only).
- No Excel reporting of any kind.
- No security test suite (injection, path traversal, secret-leakage checks).

This matches expectations — Phase 0 was scoped to bootstrap only.

## 4. Architectural integration points

- **Provider boundary**: `app/domain/` is reserved for `RepositoryProvider`
  and `RepositoryContext`. Every other package (`api`, `services`, `models`)
  must depend on `app.domain`, never on a GitHub SDK/HTTP client directly.
  This is enforced structurally by Phase 2/3, not yet by code (there is
  nothing to violate it yet).
- **Service boundary**: `app/services/` is reserved for the GitHub API
  client (Phase 5), clone service (Phase 7), and ingestion orchestration
  (Phase 11). Route handlers in `app/api/v1/` should call into services,
  never construct HTTP requests or subprocess calls themselves.
- **Persistence boundary**: `app/models/` (ORM) + `app/db/session.py`
  (`get_db` dependency) is the single persistence path. Phase 14 (Excel)
  must read through this same layer rather than re-querying GitHub or the
  filesystem independently, per the plan's "no separate repository data
  pipeline" requirement.
- **Config boundary**: all environment-derived values flow through
  `get_settings()`. No module should call `os.environ` or `os.getenv`
  directly — this keeps `GITHUB_TOKEN` handling centralized and auditable.

## 5. Risks identified

- **No database provisioned.** `DATABASE_URL` in `.env.example` assumes a
  local Postgres at `localhost:5432`. Phase 9 (and any earlier phase that
  wants to persist state) needs either a real Postgres instance (e.g. via
  Docker) or a documented local setup step. Recommend adding a
  `docker-compose.yml` for local Postgres when Phase 9 starts, or falling
  back to SQLite for early development if Docker isn't available in this
  environment — to be decided at Phase 9, not now.
- **No Alembic environment yet.** `alembic` is a declared dependency but
  unconfigured. Phase 9 must run `alembic init` and wire `env.py` to
  `app.db.base.Base.metadata` before the first migration.
- **`gitpython` vs `subprocess` for cloning.** `requirements.txt` includes
  `gitpython`, but the plan (Section 9) explicitly requires "argument
  lists rather than shell interpolation" and tight control over timeouts/
  size limits for security reasons. `GitPython` shells out to the `git`
  binary internally and is generally safe when passed explicit argument
  lists (not shell strings), but Phase 7 must confirm the specific clone
  call keeps `shell=False` semantics and does not accept unsanitized
  input into any single interpolated command string. Alternative: use
  `subprocess.run(["git", "clone", ...])` directly for full control and a
  smaller dependency surface — decide in Phase 7.
- **`psycopg[binary]`** is a convenience wheel; fine for development, but
  worth revisiting for production (source build vs. binary) — not
  blocking for now.
- **No CI configured.** Tests currently only run locally. Recommend adding
  a CI workflow once Phase 5+ introduces network-dependent tests, so the
  "offline-safe by default, opt-in network tier" requirement (Plan
  Section 26/Phase 15) is actually enforced automatically.

## 6. Migration requirements

None — there is no prior GitHub integration or legacy repository-handling
code in this project to migrate away from. Phase 2 starts from a clean
slate and only needs to respect the boundaries described in Section 4
above.

## 7. Baseline test results

```
backend: pytest -q
...                                                                      [100%]
3 passed in 0.05s

frontend: npm run build
✓ built in 700ms
```

Both green. No regressions to carry into Phase 2.

## 8. Conclusion / go-ahead

The project is clean and ready for Phase 2 (Design Integration
Architecture). No rewrites are needed — Phase 2/3 should add to
`app/domain/`, `app/services/`, and `app/api/v1/` following the boundaries
established above.

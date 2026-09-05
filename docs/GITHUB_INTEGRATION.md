# AURA-X GitHub Integration

Living document, now covering Phases 0–16. Real code is the source of
truth; this file is updated to match it, not the other way around. See
`docs/AURA-X_PROJECT_STATUS_AND_PLAN.pdf` for the phase-by-phase plan and
the standalone QA/audit report for adversarial test results.

## Architecture

```
                       ┌───────────────────────────┐
                       │   RepositoryProvider (ABC) │
                       └───────────────────────────┘
                          │              │              │
                 ┌────────┘        ┌─────┘        ┌─────┘
                 ▼                 ▼               ▼
         GitHubProvider   LocalRepositoryProvider   GitLabProvider
          (implemented)         (future)              (future)
                 │
                 ▼
         RepositoryContext (normalized, provider-agnostic)
                 │
   ┌─────────────┼──────────────────────────────────────┐
   ▼             ▼                                       ▼
Repository   Evolution / Risk / Test                 Reporting
Intelligence     Planning                            (API / Dashboard / Excel)
```

**Rule:** everything below the `RepositoryContext` line depends only on
`app.domain.RepositoryContext`. Nothing outside `app/domain` and
`app/services` may import a GitHub-specific type or call the GitHub HTTP
API directly — enforced both by review and by
`tests/test_architecture_boundaries.py` (grep-based: zero
`GitHubProvider`/`GitHubApiClient` imports outside `app/services`, zero
`subprocess` usage outside `clone_service.py`, zero `shell=True` anywhere,
exact route-enumeration). Repository Intelligence / Evolution / Risk /
Test Planning are **out of this system's scope** — they don't exist in
this codebase; `RepositoryContext` is their intended, tested contract
(Phase 12), with no fabricated consumer built to exercise it.

### RepositoryProvider interface

Defined in `app/domain/repository_provider.py`; implemented by
`GitHubProvider` (`app/services/github_provider.py`), the only class
allowed to talk to `api.github.com` or spawn `git`.

| Method | Returns | Notes |
|---|---|---|
| `fetch_metadata(owner, repo)` | `RepositoryMetadata` | id, description, default_branch, visibility, stats, timestamps |
| `list_branches(owner, repo)` | `list[BranchInfo]` | name + head commit sha, one marked `is_default` |
| `get_commit_history(owner, repo, branch, limit)` | `list[CommitInfo]` | bounded by `min(limit, settings.max_commit_history)` |
| `get_languages(owner, repo)` | `dict[str, int]` | language → byte count, as reported by GitHub |
| `clone(owner, repo, branch, target_dir)` | `CloneResult` | isolated, sandboxed, argument-list subprocess only |

### RepositoryContext schema

Defined in `app/domain/repository_context.py`; reconstructed for a
persisted run by `app/services/context_builder.py::build_repository_context()`,
which every downstream consumer (REST API, Excel export, and any future
analysis module) is required to go through rather than querying ORM rows
directly.

| Field | Type | Set during |
|---|---|---|
| `repository_id` | `str` | ingestion start (DB primary key) |
| `provider` | `str` (`"github"`) | provider selection |
| `source_url` | `str` | user input, normalized |
| `owner` / `repository_name` | `str` | URL parsing |
| `local_path` | `str \| None` | clone |
| `selected_branch` / `default_branch` | `str \| None` | branch resolution / metadata fetch |
| `commit_sha` | `str \| None` | clone verification (`git rev-parse HEAD`) |
| `metadata` | `RepositoryMetadata \| None` | metadata fetch |
| `languages` | `dict[str, int]` | scan (merges GitHub-reported + on-disk detection) |
| `file_tree` | `list[FileEntry]` | repository scan |
| `test_frameworks` | `list[str]` | scan (pytest/unittest/tox/nox, Jest/Vitest/Mocha) |
| `evolution_signals` | churn/co-change | scan, from real git log |
| `analysis_status` | `IngestionStatus` | state machine |
| `created_at` / `updated_at` | `datetime` | ingestion lifecycle |

### Ingestion state machine

```
PENDING → VALIDATING → FETCHING_METADATA → FETCHING_BRANCHES → CLONING → SCANNING → READY
                 └──────────────────────────────────────────────────────────→ FAILED
```

`FAILED` is reachable from any non-terminal state; `READY`/`FAILED` are
terminal. Enforced both in-memory (`RepositoryContext.transition_to()`,
`app/domain/repository_context.py`) and at the database layer
(`persistence_service.transition_analysis_run()`, same
`ALLOWED_TRANSITIONS` table, same `InvalidStateTransitionError`).

## URL validation

`app/domain/github_url.py::parse_github_url()`. Accepts
`https://github.com/owner/repo`, `.../repo.git`, `.../repo/`, and
`http://`/`www.` variants; rejects anything else with a structured error:

- `InvalidRepositoryUrlError` (`INVALID_REPOSITORY_URL`) — empty input,
  wrong scheme, missing hostname, embedded credentials, missing
  owner/repo segments, invalid owner/repo character set, reserved repo
  names (`.`, `..`, `.git`), path traversal sequences (`..`, `%2e%2e`,
  backslashes), control characters (incl. CR/LF header-injection
  attempts), overlong input (>2048 chars).
- `UnsupportedRepositoryProviderError` (`UNSUPPORTED_REPOSITORY_PROVIDER`)
  — well-formed URL, host is not `github.com`/`www.github.com` (covers
  lookalike hosts like `github.evil.com` and `github.com.evil.com`).

Owner/repo are validated against GitHub's actual naming rules before
being trusted anywhere else in the system.

## GitHub API client

`app/services/github_client.py::GitHubApiClient` is the **only** module
allowed to call `api.github.com`. Behavior:

- **Timeouts**: `settings.github_request_timeout_seconds`, raises
  `UpstreamTimeoutError` after exhausting `github_max_retries` attempts.
- **Retries**: exponential backoff (capped at 2s) on timeouts, connection
  errors, and `5xx` responses; `4xx` responses are never retried.
- **Rate limiting**: a `403` with `X-RateLimit-Remaining: 0` raises
  `RateLimitExceededError` (reset time from `X-RateLimit-Reset`); GitHub's
  secondary/abuse-detection `429` maps to the same error; a `403` without
  rate-limit headers raises `RepositoryAccessDeniedError` instead.
- **Auth**: when `settings.has_github_token()` is true, sends
  `Authorization: Bearer <token>`. Never logged, in any response, or in
  any exception message — proven with a `caplog`-based test spanning a
  real successful and a real failing request
  (`tests/test_security_matrix.py`).
- **Malformed responses**: invalid JSON, or a paginated response that
  isn't a JSON array, raises `MalformedUpstreamResponseError`.
- **Pagination**: `get_paginated(path, limit)` follows the GitHub `Link`
  response header (`rel="next"`) up to a caller-supplied item limit.

`app/services/github_provider.py::GitHubProvider` implements
`RepositoryProvider` on top of the client; self-registers for
`github.com`/`www.github.com` at import time, so
`get_provider_class_for_host("github.com")` resolves it without any other
module importing `GitHubProvider` directly.

## Branch resolution

`app/services/repository_service.py::resolve_branch(provider, owner, repo,
requested_branch)`:

- `requested_branch=None` → the branch GitHub marks as the repository's
  actual default.
- `requested_branch="some-name"` → that branch's `BranchInfo` or
  `BranchNotFoundError` (`BRANCH_NOT_FOUND`) if it doesn't exist — never
  silently substitutes a different branch than requested.

Verified live against `github.com/octocat/Hello-World`
(`tests/test_github_integration_live.py`, skipped by default — run with
`pytest --run-network`), and against `github.com/octocat/Hello-World`
manually as part of Phase 16's real end-to-end walk (see below).

## Secure cloning

`app/services/clone_service.py::clone_repository()` clones into
`workspace_root/{repository_id}/source` via **argument-list
`subprocess.run` calls only** — `shell=True` is never used anywhere in
the codebase (grep-enforced). Branch names are validated before ever
reaching the subprocess argument list (reject empty, leading `-`, `..`,
null bytes, control characters). `clone_timeout_seconds` and
`max_repository_size_mb` are enforced; the actual checked-out commit SHA
is read via `git rev-parse HEAD` (never trusted from the GitHub API
alone) and compared for consistency. Repository code is never executed —
no `setup.py`, no install scripts, no hooks.

## RepositoryContext construction (scan)

`app/services/repository_scan_service.py` walks the cloned tree
respecting `.gitignore` (via `pathspec`), excluding `.git`/
`node_modules`/venvs/caches/binaries/oversized files; detects languages
(extension + GitHub-reported + dependency files) and test frameworks
(pytest/unittest/tox/nox, Jest/Vitest/Mocha) by filename only — file
content is read for a small fixed set of known config filenames, bounded
to ~1MB, never passed to `eval`/`exec`/a subprocess. Git evolution
signals (churn, co-change) are computed from the real `git log` of the
cloned repository.

## Persistence

`app/models/*` (SQLAlchemy `Repository`/`Branch`/`AnalysisRun`), migrated
via Alembic (`backend/alembic/`). SQLite is the default for development
(`sqlite:///.workspace/aurax.db`); override `DATABASE_URL` for Postgres in
production. **A fresh checkout needs `alembic upgrade head` run once**
before the first request — this isn't automatic, and there is no
migration-on-startup hook. (`create_db_engine()` does create a missing
*directory* for a SQLite file path automatically — a real gap found live
during Phase 16 and fixed; it does not create the tables themselves.)
FK cascades (`ondelete=CASCADE`/`SET NULL`) are enforced; SQLite requires
`PRAGMA foreign_keys=ON` per connection, wired via a `connect` event
listener.

## REST API

`app/api/v1/repositories.py`, mounted under `/api/v1`:

| Method & path | Purpose |
|---|---|
| `POST /repositories` | Start ingestion (`{"source_url": ..., "branch": ...}`); returns 202 with the in-progress `AnalysisRun` |
| `GET /repositories` | Paginated list (`limit`, `offset`) |
| `GET /repositories/{id}` | Repository profile |
| `GET /repositories/{id}/branches` | Persisted branches |
| `GET /repositories/{id}/commits` | Persisted commit history |
| `POST /repositories/{id}/refresh` | Re-run ingestion, optionally on a different `branch` |
| `GET /analysis-runs/{run_id}` | Poll status; force-fails a genuinely stuck run past `stuck_run_timeout_seconds` |
| `GET /analysis-runs/{run_id}/export.xlsx` | Real downloadable Excel report (see below) |

Every domain error maps to a correct HTTP status and a `{code, message}`
body — never a raw stack trace.

## Asynchronous status tracking

`app/services/ingestion_service.py` splits ingestion into a fast
synchronous part (URL validation through metadata fetch — errors here are
plain HTTP errors, no durable row yet) and a slow part run in a FastAPI
`BackgroundTasks` callback (branch resolution through clone and scan).
The background task opens its **own** fresh database session — it never
receives the original request's `Session` by reference, since
`get_db()`'s generator dependency can close that session while the
background task is still using it. Any failure transitions the run to
`FAILED` with the structured error recorded rather than propagating
(there's no request left to propagate to).

## Downstream analysis hookup

`build_repository_context()` is the single, tested entry point any real
downstream module (Repository Intelligence / Evolution / Risk / Test
Planning) would consume — none of those modules exist in this codebase;
they are out of scope by design, confirmed rather than assumed. The
contract itself is proven: one commit SHA flows unchanged from clone
through persistence through reconstruction (Phase 12's integration test).

## Dashboard

`frontend/` (React + Vite + TypeScript): paste a URL, optionally pick a
branch, watch real progress (driven by polling the real status endpoint,
never simulated), view the resulting profile. 12 component tests
(Vitest + Testing Library) exercise the real component tree against a
mocked `fetch`. **Confirmed working in a real browser** (Phase 16): the
onboarding form, submission, real rendered profile, and the branch-switch
button were all driven for real in Chrome against the real backend,
using a real public repository — the profile data matched an independent
`curl`-only walk of the same repository exactly.

## Excel reporting

`GET /api/v1/analysis-runs/{run_id}/export.xlsx` →
`app/services/excel_report_service.py::generate_repository_report()`
builds an in-memory `.xlsx` (never touches disk) directly from
`RepositoryContext`, adding no new fact-gathering logic: Summary,
Languages, Files, Test Frameworks sheets. Untrusted upstream content
(e.g. a repository description) appears only as inert display text —
proven with a dedicated leakage test that injects fake token-like
strings and scans every cell of every sheet.

## Authentication

`GITHUB_TOKEN` (optional, backend-only, `SecretStr`) — see
`app/core/config.py`. Public repositories work without it; a token
raises GitHub's rate limits. Never logged, never returned in any API
response, never written to a report, never present in a database column.

## Security

- URL/path validation before any network or filesystem action.
- Clone via argument-list subprocess calls only, never shell strings.
- Clone timeout, repository size limit, workspace isolation.
- No repository code is ever executed during ingestion.
- Secrets never logged, never returned in API responses, never written to
  Excel — enforced by `SecretStr` plus a consolidated, system-boundary
  security test suite (`tests/test_security_matrix.py`, Phase 15) in
  addition to the original per-module tests.
- A real GitHub Actions workflow (`.github/workflows/backend-tests.yml`)
  runs the full offline suite on every push/PR.

## Error handling

Structured error codes (`app/domain/errors.py`), every one of them
actually raised somewhere in the codebase and mapped to an HTTP status by
`app/api/error_handlers.py`:

`INVALID_REPOSITORY_URL`, `UNSUPPORTED_REPOSITORY_PROVIDER`,
`REPOSITORY_NOT_FOUND`, `REPOSITORY_ACCESS_DENIED`, `BRANCH_NOT_FOUND`,
`RATE_LIMITED`, `TIMEOUT`, `UPSTREAM_UNAVAILABLE`,
`MALFORMED_RESPONSE`, `CLONE_FAILED`, `REPOSITORY_TOO_LARGE`,
`INVALID_STATE_TRANSITION`, `REPOSITORY_SCAN_FAILED`.

## Testing

351 backend tests (`backend/tests/`) + 12 frontend tests
(`frontend/src/**/*.test.tsx`). Offline by default; a 6-test network tier
(real calls to `github.com/octocat/Hello-World`) runs with
`pytest --run-network` or `AURA_X_RUN_NETWORK_TESTS=1`. 96% measured line
coverage (`pytest --cov=app --cov-report=term-missing`). See the
standalone QA report for the full adversarial-testing history, including
every bug found and fixed and the load-bearing spot-checks proving each
regression test genuine.

## Limitations (current)

- Only `GitHubProvider` is implemented; `LocalRepositoryProvider` and
  `GitLabProvider` are named in the abstraction but don't exist.
- Private-repository cloning is deferred — cloning never uses a token
  today (public repositories only); a real design (`-c
  http.extraHeader`, never a URL-embedded token) is needed before this is
  added.
- No concurrency lock on the clone workspace — a live risk under real
  concurrent ingestion traffic, not yet built.
- Repository Intelligence / Evolution / Risk / Test Planning don't exist
  in this codebase — confirmed out of scope, not silently assumed done.
  This is the only step of the plan's full end-to-end walk that doesn't
  run, and it never will from inside this codebase.

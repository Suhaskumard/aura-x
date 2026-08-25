# AURA-X GitHub Integration

Living document. Updated at the end of every phase in
`docs/GITHUB_INTEGRATION_PLAN.pdf`. This revision covers Phase 13
(dashboard integration).

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
(app/analysis/, Phase 12)                             (partial: API is
                                                        Phase 10/11;
                                                        Dashboard/Excel
                                                        not yet built)
```

**Rule:** everything below the `RepositoryContext` line depends only on
`app.domain.RepositoryContext`. Nothing outside `app/domain` and
`app/services` (Phase 5+) may import a GitHub-specific type or call the
GitHub HTTP API directly. This is enforced by code review and by the
provider factory being the only place that instantiates a concrete
provider. `app/analysis/` (Phase 12) follows the same rule from the
consumer side: it imports `app.domain.RepositoryContext` and nothing
GitHub-specific.

### RepositoryProvider interface

Defined in `app/domain/repository_provider.py`. Abstract methods:

| Method | Returns | Notes |
|---|---|---|
| `fetch_metadata(owner, repo)` | `RepositoryMetadata` | id, description, default_branch, visibility, stats, timestamps |
| `list_branches(owner, repo)` | `list[BranchInfo]` | name + head commit sha |
| `get_commit_history(owner, repo, branch, limit)` | `list[CommitInfo]` | bounded, newest first |
| `get_languages(owner, repo)` | `dict[str, int]` | language → byte count, as reported by the provider |
| `get_commit_file_changes(owner, repo, sha)` | `list[FileChange]` | per-file additions/deletions/status for one commit; not in the bulk commit-list response, so callers fetch it for a bounded window of commits (Phase 8 — implemented) |
| `clone(owner, repo, branch, target_dir)` | `CloneResult` | isolated, sandboxed, argument-list subprocess only (Phase 7 — implemented) |

`GitHubProvider` (Phase 5+) implements this against the real GitHub REST
API. It is the only class in the codebase allowed to import an HTTP client
configured with `github_api_base_url` / `github_token`.

### RepositoryContext schema

Defined in `app/domain/repository_context.py` as a plain, serializable
dataclass — no ORM or GitHub SDK types leak into it, so downstream modules
(and their tests) never need network access or a database to construct one.

| Field | Type | Set during |
|---|---|---|
| `repository_id` | `str` | ingestion start (generated) |
| `provider` | `str` (`"github"`, ...) | provider selection |
| `source_url` | `str` | user input, normalized |
| `owner` | `str` | URL parsing (Phase 4) |
| `repository_name` | `str` | URL parsing (Phase 4) |
| `local_path` | `str \| None` | clone (Phase 7 — implemented) |
| `selected_branch` | `str \| None` | branch resolution (Phase 6) |
| `default_branch` | `str \| None` | metadata fetch (Phase 6) |
| `commit_sha` | `str \| None` | clone verification (Phase 7 — implemented) |
| `metadata` | `RepositoryMetadata \| None` | metadata fetch (Phase 6) |
| `branches` | `list[BranchInfo]` | branch fetch (Phase 6) |
| `languages` | `dict[str, int]` | language detection (Phase 8 — implemented) |
| `file_tree` | `list[FileEntry]` | repository scan (Phase 8 — implemented) |
| `git_history` | `list[CommitInfo]` | commit history fetch (Phase 6); `changed_files` enriched for a bounded window (Phase 8 — implemented) |
| `test_frameworks` | `list[str]` | test-framework detection (Phase 8 — implemented) |
| `evolution_signals` | `EvolutionSignals \| None` | churn/co-change/concentration signals (Phase 8 — implemented) |
| `analysis_status` | `IngestionStatus` | state machine (Phase 3); mirrored onto a persisted `AnalysisRun.status` (Phase 9 — implemented) |
| `created_at` / `updated_at` | `datetime` | ingestion lifecycle |

### Ingestion state machine

```
PENDING → VALIDATING → FETCHING_METADATA → FETCHING_BRANCHES → CLONING → SCANNING → READY
                 └──────────────────────────────────────────────────────────→ FAILED
```

`FAILED` is reachable from any non-terminal state. `READY` and `FAILED`
are terminal. Implemented as `IngestionStatus` (enum) +
`ALLOWED_TRANSITIONS` in `app/domain/repository_context.py`; enforced by
`RepositoryContext.transition_to(...)`, which raises `InvalidStateTransition`
on an illegal jump. Phase 9 backs this with a persisted state machine on
`AnalysisRun.status`, enforcing the same `ALLOWED_TRANSITIONS` allow-list
-- see "Database Persistence" below.

## URL validation (Phase 4 — implemented)

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

Owner/repo are validated against GitHub's actual naming rules (owner:
alphanumeric/hyphen, no leading/trailing hyphen, ≤39 chars; repo:
alphanumeric/`.`/`_`/`-`, ≤100 chars) before being trusted anywhere else
in the system. 34 unit tests in `tests/test_github_url.py`, including a
security matrix (path traversal, header injection, shell metacharacters,
credential-in-URL, lookalike hosts).

## GitHub API usage (Phase 5 — implemented)

`app/services/github_client.py::GitHubApiClient` is the **only** module
allowed to call `api.github.com`. It wraps `httpx.Client` and implements:

- `get_json(path)` — single-resource GET with retry/error translation.
- `get_paginated(path, limit)` — follows the GitHub `Link` response header
  (`rel="next"`) up to a caller-supplied item limit.

Behavior:

- **Timeouts**: `settings.github_request_timeout_seconds`, raises
  `UpstreamTimeoutError` after exhausting `github_max_retries` attempts.
- **Retries**: exponential backoff (capped at 2s) on timeouts, connection
  errors, and `5xx` responses; `4xx` responses are never retried.
- **Rate limiting**: a `403` with `X-RateLimit-Remaining: 0` raises
  `RateLimitExceededError` including the reset time from
  `X-RateLimit-Reset`; a `403` without those headers (private repo /
  insufficient scope) raises `RepositoryAccessDeniedError` instead.
- **Auth**: when `settings.has_github_token()` is true, sends
  `Authorization: Bearer <token>` — the token is read once from
  `SecretStr.get_secret_value()` and never logged or included in any
  raised exception message.
- **Malformed responses**: invalid JSON, or a paginated response that
  isn't a JSON array, raises `MalformedUpstreamResponseError` rather than
  propagating a `ValueError`/`TypeError`.

`app/services/github_provider.py::GitHubProvider` implements
`RepositoryProvider` on top of the client and maps raw GitHub JSON into
`RepositoryMetadata`, `BranchInfo`, `CommitInfo`:

- `fetch_metadata` → `GET /repos/{owner}/{repo}`
- `list_branches` → fetches metadata (for `default_branch`) then
  `GET /repos/{owner}/{repo}/branches`, marking the matching branch
  `is_default=True`
- `get_commit_history(branch, limit)` → `GET /repos/{owner}/{repo}/commits?sha={branch}`,
  bounded by `min(limit, settings.max_commit_history)`
- `get_languages` → `GET /repos/{owner}/{repo}/languages`
- `clone(owner, repo, branch, target_dir)` → delegates to
  `app/services/clone_service.py::clone_repository`, passing the repo's
  HTTPS clone URL (`https://github.com/{owner}/{repo}.git`) and, when
  `settings.has_github_token()` is true, the token

`GitHubProvider` self-registers for `github.com` and `www.github.com` when
`app.services` is imported (`register_provider(...)` at module import
time), so `get_provider_class_for_host("github.com")` resolves it without
any other module importing `GitHubProvider` directly.

Not yet called from anywhere else in the app — no route or service wires
this in yet (that starts at Phase 6/10). 30 new tests
(`tests/test_github_client.py`, `tests/test_github_provider.py`) using
`respx` to mock every GitHub response; zero real network calls in the
test suite.

## Branch resolution (Phase 6 — implemented)

`app/services/repository_service.py::resolve_branch(provider, owner, repo,
requested_branch)`:

- `requested_branch=None` → returns the branch `GitHubProvider.list_branches`
  marked `is_default=True` (derived from the repository's real
  `default_branch` metadata field).
- `requested_branch="some-name"` → returns that branch's `BranchInfo`
  (including its `head_commit_sha`) or raises `BranchNotFoundError`
  (`BRANCH_NOT_FOUND`) if it doesn't exist. Branch names are matched
  case-sensitively, matching GitHub's own semantics.
- Never silently substitutes a different branch than what was requested.

This is provider-agnostic — it only calls `RepositoryProvider` interface
methods, so it works unchanged for any future provider.

Tested two ways:
- `tests/test_repository_service.py` — unit tests against an in-memory
  `StubProvider`, no network.
- `tests/test_github_integration_live.py` — real integration tests against
  `github.com/octocat/Hello-World` (metadata, branches, branch resolution,
  bounded commit history, languages). Skipped by default; run explicitly
  with `pytest --run-network` or `AURA_X_RUN_NETWORK_TESTS=1 pytest`, so
  the default test run never depends on internet access. Verified passing
  live as of Phase 6.

## Secure repository cloning (Phase 7 — implemented)

`app/services/clone_service.py::clone_repository(...)` is the **only**
module allowed to invoke the `git` binary — mirrors the "one module owns
the external boundary" rule already applied to `GitHubApiClient` for the
REST API. Generic over its source (a `clone_url` string), so it has no
GitHub-specific knowledge and any future provider (GitLab, local) can
reuse it unchanged.

Sandboxing, in the order it's applied:

- **Argument-list only**: `subprocess.run([...], shell=False)`, never a
  shell string — no argument (owner, repo, branch, or a token) can smuggle
  a shell metacharacter.
- **Workspace containment**: `target_dir` must resolve inside
  `settings.workspace_root` and must not already exist (checked via
  `Path.resolve()` + `is_relative_to`), or `CloneFailedError` is raised
  before any subprocess runs. `app/services/repository_service.py::build_clone_target_dir(...)`
  generates a fresh `{owner}__{repo}__{uuid4}` directory per clone so
  concurrent or repeated ingestions of the same repo can never collide.
- **Input validation**: `owner`/`repo` are re-validated against GitHub's
  naming rules (`app/domain/github_url.py::validate_owner_repo`, shared
  with URL parsing) and `branch` against a conservative ref-name allowlist
  that rejects a leading `-` (would otherwise be parsed as a `git` flag —
  e.g. `--upload-pack=...`) and `..`/backslash sequences. Validation
  happens even though callers are expected to have already validated
  upstream (defense in depth).
- **Shallow, single-branch clone**: `--depth 1 --branch <branch>
  --single-branch --no-tags`, bounding both clone time and history
  fetched.
- **Timeout**: `settings.clone_timeout_seconds`; on
  `subprocess.TimeoutExpired` the partial workspace is removed and
  `CloneFailedError` raised.
- **Size limit**: after cloning, the workspace is walked and summed;
  over `settings.max_repository_size_mb` removes the workspace and raises
  `RepositoryTooLargeError`.
- **Commit verification**: `git -C <target_dir> rev-parse HEAD` is run
  and validated against a sha regex — `commit_sha` on the returned
  `CloneResult` is the actually-cloned commit, not a value trusted from
  the branch-resolution step, since the remote's branch head can move
  between resolving the branch and finishing the clone.
- **Token handling**: an optional GitHub token is passed as a
  process-scoped `-c http.extraheader="AUTHORIZATION: bearer <token>"`
  override — applies only to that one `git` invocation and is never
  embedded in the clone URL or persisted into the cloned repository's
  `.git/config` (verified by
  `tests/test_clone_service.py::test_clone_does_not_write_token_into_cloned_repo_config`).
  If a `git` failure's stderr happens to echo the token, it's redacted
  before being placed in a `CloneFailedError` message
  (`test_clone_failure_redacts_token_from_error`).
- **Windows cleanup**: `git` leaves some files under `.git` read-only on
  Windows; a plain `shutil.rmtree` aborts on the first one. `_safe_rmtree`
  clears the read-only bit and retries via `onexc`/`onerror` so cleanup
  always actually removes the partial workspace instead of silently
  leaving it on disk.

Tested in `tests/test_clone_service.py` against a real local git
repository created with `git init`/`commit` in a pytest tmp dir (no
network) — covers the happy path, workspace-containment rejection,
already-exists rejection, invalid branch names (including a
`--upload-pack=...` injection attempt), a nonexistent branch, the size
limit, a mocked timeout, and token redaction/non-persistence. A real
network clone against `github.com/octocat/Hello-World` is added to
`tests/test_github_integration_live.py::test_clone_real_repository`
(same `--run-network` gate as the rest of that file).
`tests/test_github_provider.py` covers `GitHubProvider.clone`'s plumbing
(HTTPS URL construction, token pass-through) against a mocked
`clone_repository`, without touching git or the network.

Wired into the ingestion pipeline in Phase 10 --
`app/services/ingestion_orchestrator.py::ingest_github_repository` calls
`provider.clone(...)` after branch selection and drives
`RepositoryContext.transition_to(CLONING)` / `local_path` / `commit_sha`
from the returned `CloneResult`, exactly as anticipated here.

## Constructing RepositoryContext (Phase 8 — implemented)

Turns a cloned working tree + already-fetched API metadata into the fully
populated `RepositoryContext` the rest of AURA-X consumes. Each concern is
its own small, pure/read-only module under `app/services/`:

- **`file_scanner.py::scan_repository_tree(root)`** — walks the cloned
  tree and returns `list[FileEntry]`. Excludes `.git`, `node_modules`,
  virtualenvs, build/cache directories, and anything matched by the
  repo's own top-level `.gitignore`; skips oversized files
  (`DEFAULT_MAX_FILE_SIZE_BYTES` = 5MB) and binary files (known binary
  extension, or a null byte in the first 8KB). Symlinks are skipped
  entirely. Categorizes each file as `source | test | docs | config |
  build | dependency | other` from its path/extension.
- **`language_map.py`** — shared extension→language and manifest→language
  tables used by both modules below.
- **`language_detector.py::detect_languages(file_tree, github_languages)`**
  — merges GitHub's reported byte counts (authoritative when present)
  with extension-based totals from the scanned tree, plus a zero-count
  entry for any language implied by a dependency manifest
  (`requirements.txt`, `package.json`, ...) that wasn't otherwise seen.
  This keeps languages non-empty even when GitHub's linguist data is thin
  or a future provider has no language API at all.
- **`test_framework_detector.py::detect_test_frameworks(root, file_tree)`**
  / **`detect_test_directories(file_tree)`** — static, read-only
  detection (config file presence: `pytest.ini`, `conftest.py`,
  `tox.ini`, `noxfile.py`, `jest.config.*`, `vitest.config.*`,
  `.mocharc*`; or a declared dependency in `package.json` /
  `requirements*.txt` / `pyproject.toml` / `setup.cfg`). Deliberately
  does **not** infer a framework merely from `test_*.py`-shaped file
  names (equally consistent with plain stdlib `unittest`) — only reports
  what there's direct evidence for. Never imports or executes anything
  from the scanned repository.
- **`evolution_analysis.py::compute_evolution_signals(commits)`** — pure
  function over `list[CommitInfo]` producing `EvolutionSignals`
  (`app/domain/evolution.py`): per-file churn (change count +
  aggregated additions/deletions + last-changed timestamp, sorted
  hottest-first), recently-changed files (newest-commit-first, deduped),
  co-changing file pairs (files that appear together in the same commit
  more than once, top-N by co-change count), and a change-concentration
  ratio (share of total churn held by the top ~20% most-changed files).
- **`dependency_scanner.py::extract_dependencies(root)`** — best-effort
  dependency name list from `requirements*.txt` / `package.json` at the
  repo root, for the Repository Profile view only (not consumed by
  Evolution/Risk).

Orchestration lives in `app/services/repository_service.py`:

- **`enrich_commit_history(provider, owner, repo, commits, limit=30)`** —
  `get_commit_history` (Phase 6) doesn't include per-file diffs (GitHub's
  commit-*list* endpoint doesn't return them). This fetches
  `provider.get_commit_file_changes(...)` for up to `limit` of the most
  recent commits (one extra API call each) and returns commits with
  `changed_files` populated; commits beyond the limit, or that already
  carry `changed_files`, pass through unchanged.
- **`assemble_repository_context(context, provider, evolution_commit_limit=30)`**
  — expects `context` already in `CLONING` with `local_path`, `metadata`,
  `branches`, and `git_history` set (Phase 5/6/7). Transitions to
  `SCANNING`, scans the tree, detects languages and test frameworks,
  enriches + analyzes commit history, and transitions to `READY` — or to
  `FAILED` with a structured `last_error` (`REPOSITORY_SCAN_FAILED` if
  `local_path` is missing; any other `RepositoryIntegrationError`
  otherwise). Mutates and returns `context`.
- **`build_repository_profile(context) -> dict`** — the "Repository
  Profile view" deliverable: identity, metadata, branch, commit SHA,
  languages, test frameworks + test directories, dependencies, a file
  inventory summary (count/size/by-category), and a git history summary.
  Never includes `local_path` (filesystem path) or a secret.

Wired into the ingestion pipeline in Phase 10 -- `ingest_github_repository`
calls `assemble_repository_context` after `provider.clone(...)`, and
`build_repository_profile`'s output is exposed via
`GET /api/v1/repositories/{id}/profile`.

Tested in `tests/test_file_scanner.py`, `tests/test_language_detector.py`,
`tests/test_test_framework_detector.py`, `tests/test_evolution_analysis.py`,
`tests/test_dependency_scanner.py` (all synthetic fixtures, no network),
and `tests/test_repository_context_assembly.py` (orchestration, using a
real on-disk fixture tree + an in-memory fake provider). A
`--run-network` end-to-end test against `octocat/Hello-World` is added to
`tests/test_github_integration_live.py`
(`test_assemble_repository_context_end_to_end_against_real_repository`);
note that repo is intentionally a single extensionless `README`, so its
detected languages can legitimately come back empty there — the
non-empty case is covered by the synthetic-fixture unit tests instead.

## Database Persistence (Phase 9 — implemented)

Persists Repository/Branch/Commit/AnalysisRun using the project's existing
SQLAlchemy/Alembic setup from Phase 0/1 -- no parallel storage system.

### Schema

Four tables, defined in `app/models/` (`Repository`, `Branch`, `Commit`,
`AnalysisRun`), all built on the shared `app.db.base.Base`:

- **`repositories`** — one row per `(provider, owner, name)`. Re-ingesting
  an already-known repository updates this row in place (fresh metadata,
  `updated_at` advanced) instead of creating a duplicate. Carries the
  provider's own id (`provider_repository_id`) separately from the row's
  own primary key, plus everything from `RepositoryMetadata`.
- **`branches`** — the repository's *current* branch set (upserted by
  name, stale branches removed on re-ingestion) — not a historical log.
- **`commits`** — the bounded commit history that's been fetched for
  analysis (mirrors `RepositoryContext.git_history`, including
  `changed_files` where enriched per Phase 8). Upserted by `sha`, never
  deleted, so a prior run's history stays retrievable even if a later run
  fetches a different window.
- **`analysis_runs`** — one row per ingestion attempt. Records exactly
  which `branch_name` / `commit_sha` / `config_snapshot` (non-secret
  settings: retry/timeout/size/history limits, evolution commit window --
  never `github_token`) were used, its `status`, and, once `READY`, the
  Repository Profile view (`result_profile`, Phase 8's
  `build_repository_profile()` output) or, once `FAILED`, the structured
  `error_code`/`error_message`.

All primary keys are app-generated UUID strings (`String(36)`) rather
than a database-native UUID type, and `analysis_runs.status` is a plain
string (the same values as `IngestionStatus`) rather than a native DB
enum -- both choices keep the schema dialect-agnostic so it runs
unchanged against SQLite (used by every test in this suite, and a valid
local-dev choice with no Docker/Postgres required) or Postgres
(production; `DATABASE_URL` in `.env.example`).

### Persisted state machine

`app/db/repository_dao.py::transition_analysis_run(db, run, new_status)`
enforces the *same* `ALLOWED_TRANSITIONS` allow-list
(`app/domain/repository_context.py`) that governs the in-memory
`RepositoryContext` (Phase 3) — a jump that's illegal in memory is
equally rejected against the persisted row, and `completed_at` is set
exactly when the run reaches `READY` or `FAILED`. `complete_analysis_run`
and `fail_analysis_run` build on it to also write `result_profile` /
`error_code`+`error_message` in the same step.

### Repository (data-access) layer

`app/db/repository_dao.py` is the only module that queries these tables —
services accept an injected `Session` (`app.db.session.get_db`) and call
into this module rather than issuing ad hoc queries. Functions:
`get_repository_by_id`, `get_repository_by_identity`,
`upsert_repository`, `upsert_branches`, `upsert_commits`,
`create_analysis_run`, `get_analysis_run`,
`list_analysis_runs_for_repository`, `transition_analysis_run`,
`complete_analysis_run`, `fail_analysis_run`.

`app/services/ingestion_persistence.py::persist_repository_context(db,
context, config_snapshot=...)` is the bridge from Phase 8's finished
`RepositoryContext` into this layer: upserts the repository/branches/
commits, creates an `AnalysisRun`, and — since the only path to `READY`
in `ALLOWED_TRANSITIONS` runs through every stage from `VALIDATING`
onward in a fixed order, and this pipeline has no branching — replays
that exact sequence on the persisted run before completing it, so the
DB-side state machine is genuinely exercised rather than short-circuited.
A `FAILED` context is recorded directly (`PENDING -> FAILED` is itself a
valid transition) without claiming which stage it reached first.
`build_config_snapshot(settings, evolution_commit_limit=...)` builds the
non-secret config snapshot.

Used directly by `POST /api/v1/repositories/github` in Phase 10. As of
Phase 11, the live background job (`run_ingestion_job`, see "REST API
Layer" below) persists incrementally as it runs instead of calling this
function -- `persist_repository_context` remains available and tested as
a one-shot "persist an already-fully-assembled RepositoryContext"
utility, just no longer on the live ingestion path.

### Migrations

Alembic, initialized at `backend/alembic.ini` / `backend/migrations/`.
`migrations/env.py` imports `app.models` (registering every model on
`Base.metadata`) and sets `sqlalchemy.url` from
`app.core.config.get_settings().database_url` — the connection string is
never duplicated in `alembic.ini` itself, matching the "config boundary"
rule the app already follows. The initial migration
(`migrations/versions/..._initial_schema_phase_9.py`) was autogenerated
from the models and verified to run both `upgrade head` and `downgrade
base` cleanly against a throwaway SQLite database (no Postgres available
in this environment to verify against directly; the schema uses no
Postgres-specific types, so the same script applies unchanged there).

### Testing

- `backend/tests/test_analysis_run_state_machine.py` — valid transition
  sequence accepted, invalid jumps rejected, `FAILED` reachable from any
  non-terminal state, terminal states reject further transitions,
  `completed_at`/`result_profile`/`error_code`+`error_message` set
  correctly.
- `backend/tests/test_repository_dao.py` — round-trip tests for each
  table plus the full repository → branch → commit → analysis-run chain,
  re-ingestion idempotency (same repository row, branches
  updated/pruned, commits accumulated), and multiple analysis runs per
  repository.
- `backend/tests/test_ingestion_persistence.py` — `persist_
  repository_context` end-to-end from a fully assembled `RepositoryContext`
  (Phase 8) through to a persisted, re-readable `AnalysisRun`, covering
  both the `READY` and `FAILED` outcomes and repeated ingestion of the
  same repository.

All of the above use `tests/conftest.py`'s `db_session` fixture — a
fresh, file-backed SQLite database per test, created from
`Base.metadata.create_all()` (not via Alembic, to keep the test suite
fast and dependency-free); the Alembic migration itself is verified
separately (see above), not by the pytest suite.

## REST API Layer (Phase 10 — implemented; ingestion made asynchronous in Phase 11)

`app/api/v1/routes/repositories.py`, mounted under `/api/v1/repositories`
via `app/api/v1/router.py`. Route handlers are thin: parse/validate the
request, call a service (`app/services/ingestion_orchestrator.py` or the
Phase 9 DAO), shape the response — no business logic lives in the route
layer itself.

### Endpoints

| Method & path | Purpose |
|---|---|
| `POST /api/v1/repositories/github` | Enqueue ingestion of a repository: `{repository_url, branch?}` -> `202` immediately with `status: "QUEUED"`; the pipeline runs as a background job (Phase 11). |
| `GET /api/v1/repositories` | Paginated list (`page`, `page_size` query params), newest-updated first; each item's `latest_status` reflects live progress. |
| `GET /api/v1/repositories/{id}` | Repository detail + its latest `AnalysisRun` summary (live status) — the "reuse GET /repositories/{id} for polling" option from the Phase 11 plan. |
| `GET /api/v1/repositories/{id}/analysis-runs/{run_id}` | Poll one specific ingestion run's live status — the dedicated status-polling endpoint from the Phase 11 plan; unlike the endpoint above, this is unambiguous even if a second ingestion/refresh has started since. |
| `GET /api/v1/repositories/{id}/branches` | The repository's currently known branches (default branch first). |
| `GET /api/v1/repositories/{id}/profile` | The Repository Profile view (Phase 8's `build_repository_profile()`) from the latest **READY** analysis run. |
| `GET /api/v1/repositories/{id}/commits` | Paginated commit history, newest first. |
| `POST /api/v1/repositories/{id}/refresh` | Enqueue re-ingestion of an already-known repository (optionally with a different `branch`) — same `202`/background-job behavior as `.../github`; adds a new `AnalysisRun`, doesn't duplicate the `Repository` row. |

All endpoints are registered and appear in the generated OpenAPI schema
(`/docs`, `/openapi.json`) with request/response models and
per-status-code descriptions (see `responses=` on each route).

### Public status vocabulary (Phase 11)

`app/api/v1/status_mapping.py::to_public_status()` maps the internal,
persisted `IngestionStatus` (`PENDING, VALIDATING, FETCHING_METADATA,
FETCHING_BRANCHES, CLONING, SCANNING, READY, FAILED` — unchanged since
Phase 3/9) to the coarser vocabulary named in the Phase 11 plan:

| Internal (`AnalysisRun.status`, DB) | Public (every API response) |
|---|---|
| `PENDING` | `QUEUED` |
| `VALIDATING` | `VALIDATING` |
| `FETCHING_METADATA`, `FETCHING_BRANCHES` | `FETCHING` |
| `CLONING` | `CLONING` |
| `SCANNING` | `ANALYZING` |
| `READY` | `READY` |
| `FAILED` | `FAILED` |

Purely a presentation-layer mapping applied when serializing a response
(`_to_summary`, `_to_ingest_response`, `_to_latest_analysis_run`, the
`/analysis-runs/{run_id}` and `/profile` endpoints) — it never changes
what's stored or how `app/db/repository_dao.py::transition_analysis_run`
validates a transition; Phase 9's `ALLOWED_TRANSITIONS` enforcement is
untouched. `FETCHING_METADATA`/`FETCHING_BRANCHES` collapse to one public
value because both are "talking to GitHub's API"; `SCANNING` reads as
`ANALYZING` because that's a better name for what Phase 8 actually does
there (scan the tree, detect languages/tests, compute evolution signals).

### Asynchronous ingestion orchestration (Phase 11)

`app/services/ingestion_orchestrator.py` is now split into two halves,
matching how FastAPI's `BackgroundTasks` work:

- **`enqueue_ingestion(db, settings, repository_url, branch)`** /
  **`enqueue_refresh(db, settings, repository_id, branch)`** — fast and
  synchronous, run inside the request. Validate the URL (`parse_github_url`
  — raises before anything is persisted, so a malformed/unsupported URL
  still fails with nothing recorded, same as Phase 10), upsert a minimal
  `Repository` row, create a `PENDING` `AnalysisRun`, and return
  immediately. This is genuinely all the request does — cloning, scanning,
  and every other slow step happen after the response is already on its
  way back, so the frontend is never blocked regardless of repository
  size (the actual "long-running ingestion never blocks the frontend"
  goal of this phase).
- **`run_ingestion_job(run_id, settings, session_factory)`** — the real
  pipeline: `fetch_metadata` -> `list_branches` + `select_branch` ->
  `get_commit_history` + `get_languages` -> `clone` ->
  `assemble_repository_context` (Phase 8). Run as a FastAPI `BackgroundTask`
  (`background_tasks.add_task(...)`, no new queue/broker dependency —
  there was no existing one in this project per the Phase 1 audit, and
  `BackgroundTasks` is already part of the Starlette/FastAPI stack this
  app runs on). It opens its **own** DB session via an injected
  `session_factory` (see `app/db/session.py::get_session_factory`) rather
  than the request's — that session is already closed by the time a
  background task runs (FastAPI closes `Depends(get_db)`'s session after
  background tasks complete, and by then the response has already been
  sent, so reusing it would serve no purpose and risks holding a
  connection open across a slow clone).

  Crucially, `run_ingestion_job` transitions `AnalysisRun.status`
  **live** at each stage boundary — `_advance(db, run, context, status)`
  calls `transition_analysis_run` (Phase 9) and commits *before* that
  stage's real work runs, exactly mirroring the in-memory
  `RepositoryContext.transition_to` call right next to it. This is the
  core difference from Phase 10's version, which built the whole
  `RepositoryContext` first and persisted the outcome once at the end —
  correct, but not truly live: a concurrent poll mid-ingestion would have
  seen only `PENDING` the whole time, which is exactly the "simulated
  progress bar" this phase's goal explicitly rules out. A concurrent poll
  now observes each real stage the moment it starts, and only after the
  previous stage's actual work has finished — verified directly in
  `tests/test_ingestion_job.py` by having a recording provider read the
  run's *persisted* status (via a separate DB session) at the instant each
  of its methods is called.

  `assemble_repository_context` (Phase 8) still owns its own
  `CLONING -> SCANNING -> READY/FAILED` transitions on the in-memory
  context (unchanged contract) — `run_ingestion_job` mirrors only the
  `SCANNING` entry to the DB itself (there's no hook into Phase 8 to mirror
  its internal transitions one-for-one), then reads back
  `context.analysis_status` afterward to decide whether to call
  `complete_analysis_run` or `fail_analysis_run`.

  Any `RepositoryIntegrationError` raised before `assemble_repository_context`
  (metadata fetch, branch resolution, clone) is caught and turns into a
  `FAILED` `AnalysisRun` with the structured error attached — never a
  silent hang; `completed_at` is always set on the terminal transition, so
  "did this job finish" is always answerable by polling.
  `select_branch(branches, requested_branch)` (a pure function extracted
  from Phase 6's `resolve_branch`, which still fetches its own branch list
  and delegates to it) lets the job reuse the branch list it already needs
  for `RepositoryContext.branches` instead of an extra network call.

  `persist_repository_context` (Phase 9) is **not** used by the live job
  above — replaying the full transition sequence after the fact is exactly
  what Phase 11 replaces with live tracking. It's kept as-is (still
  correct, still tested by `tests/test_ingestion_persistence.py`) as a
  lower-level, still-useful capability: given an already-fully-assembled
  `RepositoryContext` from any source, persist it in one shot.

### Structured errors

`app/api/v1/error_handlers.py` registers one FastAPI exception handler
for `RepositoryIntegrationError` (the common base every domain error in
`app/domain/errors.py` extends) that renders `exc.to_dict()`
(`{"code", "message"}`) with a status code looked up from a fixed
code -> status table — no raw exception, stack trace, or GitHub payload
ever reaches an HTTP response. Two error codes were added in Phase 10:

| Code | HTTP status | Raised by |
|---|---|---|
| `ANALYSIS_NOT_READY` | 409 | `GET .../profile` when the latest run isn't `READY` yet (or none exists) |
| `UNAUTHORIZED` | 401 | `require_api_auth` when `api_auth_token` is configured and the request's bearer token doesn't match |

### API authentication

Optional and opt-in, via `Settings.api_auth_token` (`SecretStr`, same
pattern as `github_token`) — unset (default) means no auth is enforced,
matching this project's local-dev-friendly stance from Phase 0/1; there
was no pre-existing user-auth convention in the codebase to extend, so
this introduces the minimal one. When set, `POST .../github` and
`POST .../{id}/refresh` (the two mutating/write endpoints, still fast/
enqueue-only) require `Authorization: Bearer <api_auth_token>`; the
read-only `GET` endpoints are never gated, configured or not.

### Testing

- `backend/tests/test_api_repositories.py` — real HTTP calls through
  `TestClient` against the actual FastAPI app (`app.db.session.get_db`
  and `get_session_factory` both overridden to a per-test SQLite database
  via the `api_client` fixture in `tests/conftest.py`; nothing else is
  mocked or bypassed), with `respx` faking the GitHub HTTP boundary and
  `app.services.github_provider.clone_repository` monkeypatched to a real
  local fixture tree (same patterns Phases 5-7's own tests already use) —
  so these exercise the real route -> orchestrator -> Phase 8 -> Phase 9
  pipeline end-to-end. Starlette's `TestClient` runs `BackgroundTasks` to
  completion as part of the same `client.post(...)` call (verified
  directly — the *response body* reflects state from before the
  background task ran, i.e. `status: "QUEUED"`, but the database is fully
  updated by the time `client.post()` returns), so tests call `POST` once
  and then issue a follow-up `GET` to observe the real final state, with
  no sleep/poll loop needed. Covers: valid public repo ingestion (through
  to profile/branches/commits retrieval), invalid URL, unsupported host,
  branch selection, unknown branch (failed run persisted + surfaced via
  409 on `/profile`), unknown repository/run (404), refresh (same
  repository, new analysis run), pagination, and auth required/not-required.
- `backend/tests/test_ingestion_job.py` — direct tests of
  `run_ingestion_job` (no HTTP layer), using a recording `RepositoryProvider`
  registered under a throwaway hostname whose methods read the run's
  *persisted* status through a separate DB session at the instant each is
  called. Directly proves the two things this phase's plan asks for:
  status transitions happen in the correct order and only after the prior
  stage's real work has completed (not a replay), and a failure mid-
  pipeline (during `clone`, and separately during `fetch_metadata`)
  surfaces `FAILED` with the structured error and a set `completed_at` —
  not a silent hang.

## Downstream analysis (Phase 12 — implemented)

Per the architecture diagram at the top of this document, everything
below the `RepositoryContext` line depends only on
`app.domain.RepositoryContext` — never a GitHub-specific type, never a
re-fetch, never a filesystem re-scan. Phase 12 adds those downstream
consumers themselves (they didn't exist before this phase — see the
Phase 1 audit) as a new top-level package, `app/analysis/`, deliberately
separate from `app/services/` (the GitHub *integration* boundary: URL
parsing, the API client, cloning, scanning, persistence).

### Modules

Every module exposes one entry point, `analyze(context: RepositoryContext,
...) -> <Module>Report` — a frozen dataclass report, always carrying
`repository_id`/`commit_sha` copied straight from `context`:

- **`repository_intelligence.py`** — structural summary: language
  breakdown (from `context.languages`), file counts by category, a
  `size_classification` (`small`/`medium`/`large`, by file count — a
  documented heuristic, not LOC), `has_readme`/`has_test_directory`, and
  top-level directories. All from `context.file_tree`/`languages` —
  no re-scan.
- **`evolution_insights.py`** — interprets `context.evolution_signals`
  (the churn/co-change/concentration data
  `app/services/evolution_analysis.py` computed in Phase 8) into
  hotspot files, tightly-coupled file pairs, and a `churn_pattern` read
  (`none`/`concentrated`/`distributed`). Does no signal computation of
  its own — this is the module the phase's exit criteria specifically
  asks to "verify actually consumes" Phase 8's signals, so it's built to
  be a thin, direct reader of them, not a parallel computation.
- **`dependency_analysis.py`** — dependency inventory
  (`app/services/dependency_scanner.py::extract_dependencies`, reading
  `context.local_path` — already on the context from Phase 7's clone, not
  a new input), plus which ecosystems are present (from `context.file_tree`
  dependency-category files) and whether `requirements.txt` pins versions.
- **`risk_assessment.py`** — combines Phase 8's per-file churn
  (`context.evolution_signals.file_churn`) with a static "does a test
  file's stem contain this source file's stem" heuristic (never executes
  anything, never runs a real coverage tool — there is no code execution
  anywhere in this pipeline) to flag high-churn, apparently-untested
  source files as high risk. `overall_risk_score` is the high-risk share
  of total observed churn.
- **`planning.py`** (module file deliberately not named `test_planning.py`
  — that would collide with pytest's `test_*.py` discovery glob and get
  the module itself collected as a test file) — turns Risk Assessment's
  high-risk files into concrete `TestRecommendation`s, naming the
  already-detected framework (`context.test_frameworks`) in the reason
  where one exists. Accepts an optional pre-computed `risk_report` (the
  pipeline below passes one to avoid computing it twice) but still works
  from `context` alone if omitted, computing it internally via
  `risk_assessment.analyze(context)`.

### Pipeline

`app/analysis/pipeline.py::run_downstream_analysis(context)` runs all
five in order and returns a `DownstreamAnalysisResult` bundling every
report. Requires `context.analysis_status == READY` (raises `ValueError`
otherwise) — "the **completed** RepositoryContext" per this phase's own
framing; a context that never finished ingestion would produce
misleadingly empty reports rather than a real analysis.

Because every report's `repository_id`/`commit_sha` is copied directly
from the single `context` passed in — never independently re-derived —
consistent repository/branch/commit selection across every downstream
stage (this phase's second task) is guaranteed by construction, not by a
runtime cross-check.

### Testing

- `backend/tests/test_repository_intelligence.py`,
  `test_evolution_insights.py`, `test_dependency_analysis.py`,
  `test_risk_assessment.py`, `test_planning.py` — unit tests per module
  against synthetic `RepositoryContext` fixtures (no clone, no network).
- `backend/tests/test_analysis_pipeline.py` — the integration test this
  phase's plan asks for: builds one real, fully-assembled `READY`
  `RepositoryContext` (via Phase 8's `assemble_repository_context` against
  a real on-disk fixture tree, same pattern as
  `test_repository_context_assembly.py`) with a file churned across three
  fixture commits and no matching test file, then runs
  `run_downstream_analysis` and verifies: the same `repository_id`/
  `commit_sha` appears unchanged on all five reports; Evolution's report
  matches `context.evolution_signals` exactly (same hotspot, same churn
  count — not recomputed or faked); and that same file flows all the way
  through as Risk Assessment's top high-risk file and Test Planning's
  recommendation, while a file with a matching test file does not. Also
  covers dependency/ecosystem detection reading from the same
  `local_path`, and the `READY`-only guard.

### Not yet done

Per the phase's own deliverable list ("downstream module entry points"
only), Phase 12 stops at the service layer: `run_downstream_analysis` is
not called from the ingestion job (Phase 11), not exposed via the API,
and its reports aren't persisted. Nothing in the remaining plan (Phase
13 Dashboard, Phase 14 Excel, Phase 15 test suite, Phase 16 end-to-end
validation) allocates that wiring to a specific phase either — Phase 16's
walkthrough explicitly ends with "hand off to downstream analysis" as
the last step, matching this phase's scope of exposing the entry points
without yet wiring them to run automatically.

## Dashboard Integration (Phase 13 — implemented)

`frontend/` — a single-page onboarding dashboard wired entirely to the
real `/api/v1/repositories` endpoints (Phase 10-11). No hardcoded
repository cards, no simulated progress: every value rendered comes from
an actual HTTP response.

### Flow

The API has no "preview repository info before starting analysis"
endpoint (`POST .../github` both looks up and starts ingestion in one
call), so branch selection happens after the fact rather than before, as
a re-analysis action once real branch data exists:

1. **Repository list** (`RepositoryList.tsx`) — `GET /api/v1/repositories`,
   rendered as real cards (owner/name, description, primary language,
   stars, forks, live `latest_status`). Empty state when nothing's been
   analyzed yet, not a fake placeholder card.
2. **Onboarding form** (`OnboardingForm.tsx`) — paste a URL (+ optional
   branch), `POST /api/v1/repositories/github`. Structured validation
   errors (`ApiError.code`/`message` from the backend's `{code, message}`
   body) are shown inline, not swallowed.
3. **Live progress** (`IngestionProgress.tsx` + `usePolling.ts`) — polls
   `GET /api/v1/repositories/{id}/analysis-runs/{run_id}` every 1.5s. The
   stage list (`Queued → Validating → Fetching → Cloning → Analyzing →
   Ready`) highlights the current stage from the polled response only —
   there is no timer, animation, or client-side simulation of progress.
   `usePolling` stops once `status` is `READY` or `FAILED`.
4. **Repository Profile** (`RepositoryProfileView.tsx`) — once `READY`,
   fetches `GET .../profile` and `GET .../branches` and renders exactly
   what the plan asks for: name, owner, description, selected branch,
   commit SHA, languages (as percentage bars from the profile's
   `languages` byte counts), file/size/commit statistics, detected test
   frameworks, dependencies, and status. Also offers "Re-analyze this
   branch" — a real `<select>` populated from `GET .../branches`, calling
   `POST .../refresh` with the chosen branch, which is genuine branch
   selection backed by real data (see the note on the two-step flow
   above).
5. **Failure view** — the structured `error_code`/`error_message` from a
   `FAILED` run, plus a "Retry analysis" button (`POST .../refresh`).

### API client

`frontend/src/api.ts` — typed request functions and response interfaces
mirroring `backend/app/api/v1/schemas.py` field-for-field (including the
public status vocabulary from Phase 11: `QUEUED | VALIDATING | FETCHING
| CLONING | ANALYZING | READY | FAILED`). A non-2xx response is parsed
into `ApiError { code, message, status }` from the backend's structured
error body, so validation/not-found/rate-limit/etc. errors surface with
their real code and message rather than a generic "request failed."

### Verification

No frontend test framework is configured in this project (`Phase 15`
covers the test suite); this phase's own test requirement is a manual/
E2E browser walkthrough, which was performed for real: `npm run build`
(TypeScript + Vite build, clean), the backend run against a temporary
SQLite database (`alembic upgrade head`), and the dashboard driven in a
real browser against `https://github.com/psf/requests` end-to-end —
including hitting GitHub's real unauthenticated rate limit mid-run
(surfaced correctly as `RATE_LIMITED` with the reset time, via the
failure view's Retry flow) and, after the limit reset, a full run through
to a populated profile (125 files, 3.6MB, 200 commits analyzed, an
8-language breakdown, `pytest`/`tox` detected, 6 dependencies, and a
real 6-branch dropdown for re-analysis). This confirms the exit
criteria — a user can complete the full onboarding flow using only real
API data — end-to-end, not just via code review.

## Authentication

`GITHUB_TOKEN` (optional, backend-only, `SecretStr`) — see
`app/core/config.py`. Public repositories work without it. See
Section "GitHub token" in the root `README.md`.

## Security

- URL/path validation before any network or filesystem action (Phase 4).
- Clone via argument-list subprocess calls only, never shell strings
  (Phase 7 — implemented, `app/services/clone_service.py`).
- Clone timeout, repository size limit, workspace isolation (Phase 7 —
  implemented).
- No repository code is ever executed during ingestion.
- Secrets never logged, never returned in API responses, never written to
  Excel (enforced by `SecretStr` + dedicated tests, see
  `tests/test_health.py::test_health_check_never_leaks_token_value`); the
  clone token is additionally never embedded in a URL or persisted to
  `.git/config`, and is redacted from clone-failure error messages (Phase
  7).

## Error handling

Structured error codes and where each is currently raised:

| Code | Raised by |
|---|---|
| `INVALID_REPOSITORY_URL` | `app/domain/github_url.py` (Phase 4) |
| `UNSUPPORTED_REPOSITORY_PROVIDER` | `app/domain/github_url.py` (Phase 4) |
| `REPOSITORY_NOT_FOUND` | `app/api/v1/routes/repositories.py` (unknown `{repository_id}`), `app/services/ingestion_orchestrator.py::refresh_repository_ingestion` (Phase 10) |
| `REPOSITORY_ACCESS_DENIED` | `app/services/github_client.py` (Phase 5) |
| `BRANCH_NOT_FOUND` | `app/services/repository_service.py::resolve_branch` (Phase 6) |
| `RATE_LIMITED` | `app/services/github_client.py` (Phase 5) |
| `TIMEOUT` | `app/services/github_client.py` (Phase 5) |
| `UPSTREAM_UNAVAILABLE` | reserved; not yet raised |
| `MALFORMED_RESPONSE` | `app/services/github_client.py` (Phase 5) |
| `CLONE_FAILED` | `app/services/clone_service.py` (Phase 7) |
| `REPOSITORY_TOO_LARGE` | `app/services/clone_service.py` (Phase 7) |
| `REPOSITORY_SCAN_FAILED` | `app/services/repository_service.py::assemble_repository_context` (Phase 8) |
| `INVALID_STATE_TRANSITION` | `app/domain/repository_context.py` (Phase 3) |
| `ANALYSIS_NOT_READY` | `app/api/v1/routes/repositories.py` (`GET .../profile` with no `READY` run yet) (Phase 10) |
| `UNAUTHORIZED` | `app/api/v1/routes/repositories.py::require_api_auth` (Phase 10) |

Every code above maps to an HTTP status via a single table in
`app/api/v1/error_handlers.py` (Phase 10) -- see "REST API Layer" above.

## Testing

- `backend/tests/test_repository_context.py` — `RepositoryContext`
  construction, serialization round-trip, state-machine transitions
  (Phase 3). No network, no database.
- `backend/tests/test_clone_service.py` — clone sandboxing against a real
  local git repo (Phase 7). No network.
- `backend/tests/test_github_integration_live.py` — real calls (metadata,
  branches, commits, languages, clone, scan, and full
  `assemble_repository_context` end-to-end) against
  `github.com/octocat/Hello-World`. Skipped by default; run with
  `pytest --run-network` or `AURA_X_RUN_NETWORK_TESTS=1 pytest`.
- `backend/tests/test_file_scanner.py`, `test_language_detector.py`,
  `test_test_framework_detector.py`, `test_evolution_analysis.py`,
  `test_dependency_scanner.py`, `test_repository_context_assembly.py` —
  Phase 8 unit + orchestration tests, synthetic fixtures, no network.

## Limitations (current)

- Only `GitHubProvider` is implemented; `LocalRepositoryProvider` and
  `GitLabProvider` are named in the abstraction but not implemented.
- Ingestion runs as a FastAPI `BackgroundTask` within the same server
  process/worker (Phase 11) -- not a durable, separately-scaled job
  queue (Celery/RQ/arq + a broker). A job in flight when the process
  restarts or crashes is lost (its `AnalysisRun` stays stuck at whatever
  status it last reached, never reaching `READY`/`FAILED`); there's no
  retry, no persisted queue, and jobs don't survive past a single
  worker's lifetime. This matches the "per existing app architecture"
  instruction (there was no queue/broker in the project to build on --
  see the Phase 1 audit) rather than introducing new infrastructure;
  revisit if ingestion volume or reliability needs grow.
- No cap on concurrent background ingestion jobs -- many simultaneous
  `POST .../github` calls each spawn their own thread-pooled background
  task and DB session; nothing currently limits how many run at once.
- The initial migration was verified against SQLite only (no Postgres
  instance available in this environment); it uses no Postgres-specific
  types, but running it against a real Postgres instance is still
  recommended before Phase 9's persistence is relied on in production.
- API auth (`api_auth_token`) is a single shared bearer token, not a
  per-user/per-team identity system -- adequate for a single-backend
  deployment, not for multi-tenant use.
- No rate limiting or request throttling on `/api/v1/repositories` routes
  -- a client could exhaust the configured GitHub token's rate limit by
  issuing many ingestion requests. Confirmed directly during Phase 13's
  browser walkthrough: without `GITHUB_TOKEN` configured, GitHub's
  unauthenticated limit (60 requests/hour) is easy to exhaust across a
  handful of ingestions -- set `GITHUB_TOKEN` for real usage (raises it
  to 5000/hour).
- The dashboard (`frontend/`) has no automated tests -- no test framework
  is configured in this project yet (`vitest`/`@testing-library` are not
  installed); Phase 13's own test requirement is a manual/E2E browser
  walkthrough, which was performed, not an automated suite. Automated
  frontend tests are Phase 15's scope ("Comprehensive Test Suite").
- The dashboard doesn't send `Authorization` headers, so it only works
  against a backend with `api_auth_token` unset (the default). If that's
  configured, the dashboard has no UI to supply the token.
- No pagination UI on the repository list yet (`GET /repositories` is
  paginated server-side, but the dashboard always requests the first 50
  and doesn't expose page controls) -- fine at today's scale, revisit if
  the list grows past that.
- `clone()` always performs a shallow (`--depth 1`), single-branch clone;
  full history is never fetched to disk (commit history for analysis
  comes from the GitHub API, bounded by `max_commit_history`, not from the
  local clone).
- `enrich_commit_history` only fetches per-file diffs for the most recent
  `evolution_commit_limit` (default 30) commits — one GitHub API call
  each — to bound request volume; evolution signals for large histories
  are computed over that recent window, not the full history.
- Dependency extraction (`dependency_scanner.py`) is best-effort name-only
  parsing of `requirements*.txt`/`package.json`; it doesn't resolve
  lockfiles, transitive dependencies, or other ecosystems (Maven, Cargo,
  Go modules) yet.

# AURA-X GitHub Integration

Living document. Updated at the end of every phase in
`docs/GITHUB_INTEGRATION_PLAN.pdf`. This revision covers Phase 8
(constructing RepositoryContext: file inventory, language/test-framework
detection, evolution signals).

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
`app/services` (Phase 5+) may import a GitHub-specific type or call the
GitHub HTTP API directly. This is enforced by code review and by the
provider factory being the only place that instantiates a concrete
provider.

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
| `analysis_status` | `IngestionStatus` | state machine (Phase 9/11) |
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
on an illegal jump. Phase 9 will back this with a persisted state machine;
Phase 3 only needs it to hold correctly in memory.

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

Not yet wired into an API route or the ingestion state machine — that
starts at Phase 9/11, which will call `provider.clone(...)` after branch
resolution and drive `RepositoryContext.transition_to(CLONING)` /
`local_path` / `commit_sha` from the returned `CloneResult`.

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

Not yet wired into an API route — that starts at Phase 10/11, which will
call `assemble_repository_context` after `provider.clone(...)` and expose
`build_repository_profile` via `/repositories/{id}`.

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
| `REPOSITORY_NOT_FOUND` | reserved; not yet raised (Phase 9/11 route wiring) |
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
- No persistence — `RepositoryContext` is in-memory only until Phase 9.
- No API route or ingestion orchestrator calls `resolve_branch`/`clone`/
  `assemble_repository_context` yet — that starts at Phase 9/11.
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

# AURA-X GitHub Integration

Living document. Updated at the end of every phase in
`docs/GITHUB_INTEGRATION_PLAN.pdf`. This revision covers Phase 2
(architecture design) and Phase 3 (RepositoryProvider abstraction).

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
| `clone(context, target_dir)` | `CloneResult` | isolated, sandboxed, argument-list subprocess only (Phase 7) |

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
| `local_path` | `str \| None` | clone (Phase 7) |
| `selected_branch` | `str \| None` | branch resolution (Phase 6) |
| `default_branch` | `str \| None` | metadata fetch (Phase 6) |
| `commit_sha` | `str \| None` | clone verification (Phase 7) |
| `metadata` | `RepositoryMetadata \| None` | metadata fetch (Phase 6) |
| `branches` | `list[BranchInfo]` | branch fetch (Phase 6) |
| `languages` | `dict[str, int]` | language detection (Phase 8) |
| `file_tree` | `list[FileEntry]` | repository scan (Phase 8) |
| `git_history` | `list[CommitInfo]` | commit history fetch (Phase 6) |
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
- `clone(...)` → raises `NotImplementedError`; implemented in Phase 7

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

## Authentication

`GITHUB_TOKEN` (optional, backend-only, `SecretStr`) — see
`app/core/config.py`. Public repositories work without it. See
Section "GitHub token" in the root `README.md`.

## Security

- URL/path validation before any network or filesystem action (Phase 4).
- Clone via argument-list subprocess calls only, never shell strings
  (Phase 7).
- Clone timeout, repository size limit, workspace isolation (Phase 7).
- No repository code is ever executed during ingestion.
- Secrets never logged, never returned in API responses, never written to
  Excel (enforced by `SecretStr` + dedicated tests, see
  `tests/test_health.py::test_health_check_never_leaks_token_value`).

## Error handling

Structured error codes introduced so far: none yet exercised in code
(reserved names per the plan): `INVALID_REPOSITORY_URL`,
`UNSUPPORTED_REPOSITORY_PROVIDER`, `REPOSITORY_NOT_FOUND`,
`REPOSITORY_ACCESS_DENIED`, `RATE_LIMITED`, `TIMEOUT`,
`UPSTREAM_UNAVAILABLE`, `MALFORMED_RESPONSE`. Defined starting Phase 4/5.

## Testing

Phase 3 adds unit tests for `RepositoryContext` construction,
serialization round-trip, and state-machine transitions
(`backend/tests/test_repository_context.py`) — no network, no database.

## Limitations (current)

- Only `GitHubProvider` is planned; `LocalRepositoryProvider` and
  `GitLabProvider` are named in the abstraction but not implemented.
- No GitHub API calls exist yet — `RepositoryProvider` is an interface
  only as of Phase 3.
- No persistence — `RepositoryContext` is in-memory only until Phase 9.

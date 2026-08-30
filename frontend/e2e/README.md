# Frontend E2E (Playwright)

Real-browser end-to-end tests for the AURA-X dashboard, added during the
frontend QA pass.

## Running

Start both servers first:

```bash
# backend (SQLite is fine - set DATABASE_URL=sqlite:///./aurax_e2e.db in backend/.env)
cd backend && uvicorn app.main:app --port 8000

# frontend
cd frontend && npm run dev            # serves http://localhost:5173
```

Then:

```bash
npm run e2e        # chromium only
npm run e2e:all    # chromium + firefox + webkit
```

## What needs what

- Most specs use Playwright request interception (`helpers.ts` → `mockApi`) and
  need **no** network and **no** real backend beyond the dev server being up.
- Specs tagged `@network` (in `02-happy-path.spec.ts`, `11-visual.spec.ts`) do a
  real GitHub ingestion of `octocat/Hello-World`; they **skip automatically** if
  `http://localhost:8000/api/v1/health` is unreachable, and treat a
  rate-limit / network failure of the ingestion itself as a skip.

## Files

| spec | area |
|---|---|
| `01-load` | startup, console, assets, refresh, history, multi-tab isolation |
| `02-happy-path` | onboard → staged progress → profile → re-analyze (mocked + real) |
| `03-onboarding` | URL validation, edge inputs, unicode, dedupe, keyboard submit |
| `04-errors` | HTTP 400–502 matrix, malformed/HTML/empty bodies, abort, recovery cycles |
| `05-race` | stale-response guards, back-mid-load, branch-select desync, click bursts |
| `06-panels` | empty states, dep cap, big numbers, MB units, null fallbacks, unicode, long tokens |
| `07-security` | XSS via repo metadata / error fields / profile fields / branch names; secret leakage |
| `08-responsive` | 320–1920px, 80–200% zoom, live resize — no horizontal overflow |
| `09-a11y` | axe (list/profile/progress), keyboard-only workflow, focus order, accessible names |
| `10-longrun` | 20 open/back cycles, 12 re-analyze cycles, poller teardown |
| `11-visual` | screenshot capture + real-backend error paths |

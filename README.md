# AURA-X

**Autonomous Unified Reliability & Evolution Analyzer**

AURA-X ingests a real GitHub repository and runs it through an autonomous
reliability pipeline: repository intelligence, Git evolution analysis, risk
prediction, and an automated testing pipeline, with results exposed via a
REST API, a dashboard, and Excel reporting.

The full phase-wise build plan for the GitHub integration (the primary
entry point into the pipeline) is in
[`docs/GITHUB_INTEGRATION_PLAN.pdf`](docs/GITHUB_INTEGRATION_PLAN.pdf).

## Project layout

```
backend/    FastAPI service (Python) — API, GitHub integration, DB, ingestion pipeline
frontend/   React + Vite + TypeScript dashboard
docs/       Architecture, audit, and planning documents
```

## Status

**All 16 phases of the GitHub integration plan are complete.** A real
public repository genuinely enters and completes the full pipeline: paste
a URL in the dashboard and it validates the URL, fetches real metadata
and branches, clones and scans the repository, detects languages/test
frameworks/dependencies, computes Git evolution signals, persists
everything, renders a live-updating Repository Profile, and hands off to
the downstream analysis stages (Repository Intelligence, Evolution
Analysis, Dependency Analysis, Risk Assessment, Test Planning) — no mock
data, hardcoded results, or simulated progress anywhere in that path.
Excel export (identity block + language distribution) is available for
any completed analysis. The backend test suite (unit, API-client,
git-integration, API, and security tests, 264 tests) is offline-safe by
default with an opt-in network-integration tier, and runs in CI
(`.github/workflows/backend-tests.yml`).

What's *not* yet built: downstream analysis results and Excel export
aren't persisted or exposed via the API/dashboard (they run and are
verified via logs/direct calls, not user-facing yet); there's no
automated frontend test suite; `LocalRepositoryProvider`/`GitLabProvider`
remain unimplemented. See `docs/GITHUB_INTEGRATION.md` — in particular
"End-to-End Validation" and "Limitations (current)" — for the complete,
current-state detail behind every phase.

## Backend setup

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # fill in DATABASE_URL, optionally GITHUB_TOKEN
alembic upgrade head            # creates the repositories/branches/commits/analysis_runs tables
uvicorn app.main:app --reload
```

`DATABASE_URL` defaults to Postgres, but no Postgres-specific column
types are used, so a local SQLite file also works with no other setup —
e.g. `DATABASE_URL=sqlite:///./aurax.db` in `.env`, or run without a
`.env` file at all via `DATABASE_URL="sqlite:///./aurax.db" alembic
upgrade head` then `DATABASE_URL="sqlite:///./aurax.db" uvicorn
app.main:app --reload`.

Runs at http://localhost:8000 — interactive API docs at `/docs`.

Run tests:

```bash
cd backend
pytest              # offline-safe: no network access, no external DB
pytest --run-network  # also runs the live-network tier against a real
                       # small public repo (github.com/octocat/Hello-World)
```

CI (`.github/workflows/backend-tests.yml`) runs the offline suite on
every push/PR touching `backend/`; the network tier is a manual
(`workflow_dispatch`) job so a transient GitHub outage or rate limit
never blocks a normal push.

### GitHub token (optional)

Public repository analysis works without any token. Setting `GITHUB_TOKEN`
in `backend/.env` raises GitHub API rate limits and enables private
repository access (once private-repo support lands). The token is read
only on the backend, is never returned in API responses, never logged, and
never written to generated reports.

## Frontend setup

```bash
cd frontend
npm install
cp .env.example .env.local      # set VITE_API_BASE_URL if backend isn't on :8000
npm run dev
```

Runs at http://localhost:5173.

## How to analyze a repository

With both servers running (see setup above):

1. Open http://localhost:5173.
2. Paste a public GitHub repository URL (e.g.
   `https://github.com/psf/requests`) into "Analyze a repository", and
   optionally a branch name — leave it blank to use the repository's
   default branch. Click **Analyze repository**.
3. The page shows real, live ingestion progress (Queued → Validating →
   Fetching → Cloning → Analyzing → Ready), polling the backend every
   1.5s — not a simulated progress bar.
4. Once ready, the Repository Profile shows the branch, commit SHA,
   language breakdown, file/size/commit statistics, detected test
   frameworks, and dependencies. Use **Re-analyze this branch** to
   re-run ingestion against a different branch, picked from the
   repository's real branch list.
5. Behind the scenes, the same completed run is also handed off to the
   downstream analysis stages (Repository Intelligence, Evolution,
   Dependency, Risk, Test Planning) — check the backend log for a
   `Downstream analysis complete for ...` line. These results aren't
   surfaced in the dashboard yet (see Status above).

To export a completed analysis to Excel (no UI button yet — see Status):

```bash
cd backend
python -c "
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.reporting.excel_export import save_repository_workbook

engine = create_engine('YOUR_DATABASE_URL', future=True)
db = sessionmaker(bind=engine, future=True)()
save_repository_workbook(db, repository_id='...', analysis_run_id='...', path='report.xlsx')
"
```

Equivalently, from the API directly:

```bash
curl -X POST http://localhost:8000/api/v1/repositories/github \
  -H "Content-Type: application/json" \
  -d '{"repository_url": "https://github.com/psf/requests"}'
# -> 202 {"repository_id": "...", "analysis_run_id": "...", "status": "QUEUED", ...}

curl http://localhost:8000/api/v1/repositories/{repository_id}/analysis-runs/{analysis_run_id}
# poll until "status": "READY"

curl http://localhost:8000/api/v1/repositories/{repository_id}/profile
```

Without `GITHUB_TOKEN` set, GitHub's unauthenticated API limits you to 60
requests/hour, which a single ingestion of a repository with substantial
commit history can approach — set `GITHUB_TOKEN` (see above) for regular
use.

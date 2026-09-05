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

**All 16 phases complete within this project's scope** (bootstrap
through a real, live end-to-end walk of both the backend and the
dashboard) — 352 backend tests + 12 frontend tests, 96% measured backend
line coverage. See
[`docs/AURA-X_PROJECT_STATUS_AND_PLAN.pdf`](docs/AURA-X_PROJECT_STATUS_AND_PLAN.pdf)
for the phase-by-phase build history and the standalone QA report for
adversarial test results. The only thing not built is analysis this
project was never scoped to do — Repository Intelligence, Evolution,
Risk, and Test Planning are separate, future systems; see
[`docs/GITHUB_INTEGRATION.md`](docs/GITHUB_INTEGRATION.md#limitations-current)
for the full list of known limitations within scope.

## Backend setup

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
# Optional: cp .env.example .env, then edit it -- defaults to a local
# SQLite file (backend/.workspace/aurax.db) and no GitHub token, both
# fine for local use. Set DATABASE_URL there to point at Postgres instead.
alembic upgrade head             # creates/updates the database tables --
                                  # required once before first use
uvicorn app.main:app --reload
```

Runs at http://localhost:8000 — interactive API docs at `/docs`.

Run tests:

```bash
cd backend
pytest                # offline suite (default)
pytest --run-network  # also runs 6 tests that call the real GitHub API
pytest --cov=app --cov-report=term-missing   # with a coverage report
```

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

With the backend running (and the frontend, for the UI form), either use
the dashboard at http://localhost:5173, or call the API directly. Every
command below was run for real against `octocat/Hello-World` as part of
Phase 16's end-to-end verification.

```bash
# 1. Start ingestion
curl -X POST http://localhost:8000/api/v1/repositories \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://github.com/octocat/Hello-World"}'
# -> 202, with the repository id and an in-progress AnalysisRun.id

# 2. Poll status until it reaches READY or FAILED
curl http://localhost:8000/api/v1/analysis-runs/{run_id}

# 3. Browse the result
curl http://localhost:8000/api/v1/repositories/{repository_id}
curl http://localhost:8000/api/v1/repositories/{repository_id}/branches
curl http://localhost:8000/api/v1/repositories/{repository_id}/commits

# 4. Re-run on a different branch
curl -X POST http://localhost:8000/api/v1/repositories/{repository_id}/refresh \
  -H "Content-Type: application/json" -d '{"branch": "some-other-branch"}'

# 5. Download a real Excel report
curl -o report.xlsx http://localhost:8000/api/v1/analysis-runs/{run_id}/export.xlsx
```

Interactive docs (with request/response schemas) are at `/docs`.

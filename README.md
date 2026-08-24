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

**Phase 0 — bootstrap.** Backend and frontend skeletons exist and are
wired together (frontend calls the backend `/api/v1/health` endpoint).
No GitHub integration exists yet — that begins at Phase 1 (audit) in the
plan above.

## Backend setup

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # fill in DATABASE_URL, optionally GITHUB_TOKEN
uvicorn app.main:app --reload
```

Runs at http://localhost:8000 — interactive API docs at `/docs`.

Run tests:

```bash
cd backend
pytest
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

Not yet available — repository ingestion (`POST /api/v1/repositories/github`)
ships in Phase 10 of the plan. This section will be filled in with real
usage instructions once that endpoint exists.

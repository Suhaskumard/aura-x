"""
Generates docs/AURA-X_PROJECT_STATUS_AND_PLAN.pdf

An updated, status-aware version of the phase-wise GitHub integration
plan: what has actually been implemented so far (with file paths and
test counts) plus the remaining phase-by-phase plan.

Run: python generate_project_status_plan_pdf.py
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
    Table, TableStyle, PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

OUT = "AURA-X_PROJECT_STATUS_AND_PLAN.pdf"

styles = getSampleStyleSheet()

styles.add(ParagraphStyle(name="TitleBig", fontName="Helvetica-Bold", fontSize=25,
    leading=31, alignment=TA_CENTER, textColor=colors.HexColor("#0f172a"), spaceAfter=6))
styles.add(ParagraphStyle(name="Subtitle", fontName="Helvetica", fontSize=13,
    leading=18, alignment=TA_CENTER, textColor=colors.HexColor("#475569"), spaceAfter=4))
styles.add(ParagraphStyle(name="MetaCenter", fontName="Helvetica", fontSize=10,
    leading=14, alignment=TA_CENTER, textColor=colors.HexColor("#64748b")))
styles.add(ParagraphStyle(name="PhaseHeader", fontName="Helvetica-Bold", fontSize=15,
    leading=19, textColor=colors.white))
styles.add(ParagraphStyle(name="SectionHead", fontName="Helvetica-Bold", fontSize=11.5,
    leading=15, textColor=colors.HexColor("#0f172a"), spaceBefore=9, spaceAfter=4))
styles.add(ParagraphStyle(name="BodyText2", fontName="Helvetica", fontSize=9.6,
    leading=13.3, textColor=colors.HexColor("#1e293b")))
styles.add(ParagraphStyle(name="BulletText", fontName="Helvetica", fontSize=9.4,
    leading=12.8, textColor=colors.HexColor("#1e293b")))
styles.add(ParagraphStyle(name="H2", fontName="Helvetica-Bold", fontSize=14, leading=18,
    textColor=colors.HexColor("#0f172a"), spaceBefore=14, spaceAfter=8))

DONE_COLOR = colors.HexColor("#15803d")
PENDING_COLOR = colors.HexColor("#334155")


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(i, styles["BulletText"]), leftIndent=6, spaceAfter=3)
         for i in items],
        bulletType="bullet", start="•", leftIndent=14,
    )


def phase_block(number, title, status, goal, tasks, deliverables, exit_criteria):
    flow = []
    color = DONE_COLOR if status == "DONE" else PENDING_COLOR
    badge = "✓ DONE" if status == "DONE" else "PENDING"
    header = Table(
        [[Paragraph(f"PHASE {number} &nbsp;|&nbsp; {title}", styles["PhaseHeader"]),
          Paragraph(badge, ParagraphStyle(name=f"badge{number}", fontName="Helvetica-Bold",
                                           fontSize=10.5, textColor=colors.white, alignment=TA_CENTER))]],
        colWidths=[13.5 * cm, 3.5 * cm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
    ]))
    flow.append(header)
    flow.append(Spacer(1, 8))
    flow.append(Paragraph("Goal" if status == "PENDING" else "What was built", styles["SectionHead"]))
    flow.append(Paragraph(goal, styles["BodyText2"]))
    flow.append(Paragraph("Key Tasks" if status == "PENDING" else "Implementation Detail", styles["SectionHead"]))
    flow.append(bullets(tasks))
    flow.append(Paragraph("Deliverables", styles["SectionHead"]))
    flow.append(bullets(deliverables))
    flow.append(Paragraph("Exit Criteria" if status == "PENDING" else "Verified", styles["SectionHead"]))
    flow.append(Paragraph(exit_criteria, styles["BodyText2"]))
    flow.append(Spacer(1, 12))
    flow.append(HRFlowable(width="100%", color=colors.HexColor("#e2e8f0"), thickness=0.7))
    flow.append(Spacer(1, 10))
    return flow


doc = SimpleDocTemplate(
    OUT, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
    topMargin=1.6 * cm, bottomMargin=1.6 * cm,
    title="AURA-X Project Status and Plan", author="AURA-X Engineering",
)

story = []

# ---- Title Page ----
story.append(Spacer(1, 2.6 * cm))
story.append(Paragraph("AURA-X", styles["TitleBig"]))
story.append(Paragraph("Autonomous Unified Reliability & Evolution Analyzer", styles["Subtitle"]))
story.append(Spacer(1, 0.5 * cm))
story.append(Paragraph("Project Status &amp; Remaining Plan", styles["TitleBig"]))
story.append(Paragraph("GitHub Repository Integration &amp; Ingestion System", styles["Subtitle"]))
story.append(Spacer(1, 1 * cm))
story.append(Paragraph("4 of 16 phases complete &mdash; 57/57 backend tests passing", styles["MetaCenter"]))
story.append(Paragraph("Document: docs/AURA-X_PROJECT_STATUS_AND_PLAN.pdf", styles["MetaCenter"]))
story.append(Paragraph("Supersedes progress tracking in docs/GITHUB_INTEGRATION_PLAN.pdf (original plan, unchanged)", styles["MetaCenter"]))
story.append(PageBreak())

# ---- Status table ----
story.append(Paragraph("Phase Status Overview", styles["H2"]))
rows = [
    ["#", "Phase", "Status", "Notes"],
    ["0", "Bootstrap (backend + frontend skeleton)", "DONE", "FastAPI + React/Vite scaffolds, wired, tested"],
    ["1", "Audit existing project", "DONE", "docs/github_integration_audit.md"],
    ["2", "Design integration architecture", "DONE", "docs/GITHUB_INTEGRATION.md architecture section"],
    ["3", "RepositoryProvider abstraction", "DONE", "app/domain/ layer, 13 tests"],
    ["4", "GitHub URL parsing & validation", "DONE", "app/domain/github_url.py, 34 tests"],
    ["5", "GitHub API client", "PENDING", "Real HTTP calls begin here"],
    ["6", "Metadata & branch retrieval", "PENDING", ""],
    ["7", "Secure repository cloning", "PENDING", ""],
    ["8", "RepositoryContext construction (scan/lang/evolution)", "PENDING", ""],
    ["9", "Database persistence", "PENDING", "Needs Postgres provisioned + Alembic init"],
    ["10", "REST API layer", "PENDING", ""],
    ["11", "Async status tracking", "PENDING", ""],
    ["12", "Downstream analysis hookup", "PENDING", ""],
    ["13", "Dashboard integration", "PENDING", ""],
    ["14", "Excel reporting", "PENDING", ""],
    ["15", "Full test suite (security/perf)", "PENDING", ""],
    ["16", "End-to-end validation", "PENDING", ""],
]
t = Table(rows, colWidths=[0.9 * cm, 8.0 * cm, 2.0 * cm, 6.0 * cm])
t.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 8.6),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 4.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
]))
for i, row in enumerate(rows[1:], start=1):
    color = DONE_COLOR if row[2] == "DONE" else colors.HexColor("#94a3b8")
    t.setStyle(TableStyle([("TEXTCOLOR", (2, i), (2, i), color), ("FONTNAME", (2, i), (2, i), "Helvetica-Bold")]))
story.append(t)
story.append(PageBreak())

# ---- Phases: completed ----
story += phase_block(
    0, "Bootstrap", "DONE",
    "Stood up a real, runnable FastAPI backend and React/Vite/TypeScript frontend, wired to each other, "
    "before any GitHub-specific code existed.",
    tasks=[
        "backend/app/main.py, app/api/v1/router.py (health check), app/core/config.py (Settings incl. "
        "GITHUB_TOKEN as SecretStr), app/core/logging.py.",
        "backend/app/db/base.py + session.py (SQLAlchemy engine/session, no tables yet).",
        "frontend/src/App.tsx replaced with a connectivity smoke test hitting /api/v1/health.",
        "Git repository initialized; .gitignore excludes .venv/node_modules/.env/.workspace.",
    ],
    deliverables=["backend/, frontend/, README.md, .gitignore, first commit d13bf45."],
    exit_criteria="Backend boots and responds to curl; frontend npm run build succeeds; 3/3 tests passing.",
)

story += phase_block(
    1, "Audit Existing Project", "DONE",
    "Documented the Phase 0 state before Phase 2+ began: what's reusable, what's missing, integration "
    "boundaries, and risks.",
    tasks=[
        "Catalogued every backend/frontend file and its role.",
        "Identified reusable pieces: Settings, get_db(), api_router, CORS config, test client fixture.",
        "Flagged risks: no Postgres provisioned yet, no Alembic env initialized, clone-library choice "
        "(gitpython vs raw subprocess) deferred to Phase 7.",
    ],
    deliverables=["docs/github_integration_audit.md"],
    exit_criteria="Audit reviewed; baseline 3/3 tests green; no migration needed (clean slate).",
)

story += phase_block(
    2, "Design Integration Architecture", "DONE",
    "Defined the RepositoryProvider/RepositoryContext boundary so no downstream module ever imports a "
    "GitHub-specific type.",
    tasks=[
        "RepositoryProvider interface table (fetch_metadata, list_branches, get_commit_history, "
        "get_languages, clone).",
        "RepositoryContext field table matching the plan's spec exactly.",
        "Ingestion state diagram: PENDING -> VALIDATING -> FETCHING_METADATA -> FETCHING_BRANCHES -> "
        "CLONING -> SCANNING -> READY, with FAILED reachable from any non-terminal state.",
    ],
    deliverables=["docs/GITHUB_INTEGRATION.md (architecture section)."],
    exit_criteria="Design reviewed and used verbatim as the spec for Phase 3's implementation.",
)

story += phase_block(
    3, "RepositoryProvider Abstraction", "DONE",
    "Implemented the provider-agnostic domain layer with zero external dependencies (no HTTP client, no "
    "ORM, no GitHub SDK) so it is fully unit-testable offline.",
    tasks=[
        "app/domain/models.py -- RepositoryMetadata, BranchInfo, CommitInfo, FileEntry, CloneResult "
        "(frozen dataclasses).",
        "app/domain/errors.py -- structured error taxonomy (INVALID_REPOSITORY_URL, REPOSITORY_NOT_FOUND, "
        "RATE_LIMITED, CLONE_FAILED, INVALID_STATE_TRANSITION, ...).",
        "app/domain/repository_context.py -- RepositoryContext with an enforced state machine "
        "(transition_to() raises InvalidStateTransitionError on an illegal jump; terminal states have no "
        "outgoing edges).",
        "app/domain/repository_provider.py -- RepositoryProvider ABC + hostname-keyed provider registry "
        "(register_provider / get_provider_class_for_host).",
    ],
    deliverables=["app/domain/ package; tests/test_repository_context.py, tests/test_repository_provider.py "
                  "(13 tests)."],
    exit_criteria="16/16 tests passing (3 baseline + 13 new); no network or database dependency in this layer.",
)

story += phase_block(
    4, "GitHub URL Parsing and Validation", "DONE",
    "First code that touches real (untrusted) user input. Normalizes a GitHub URL into (owner, repo) or "
    "rejects it with a structured, actionable error before anything downstream runs.",
    tasks=[
        "app/domain/github_url.py::parse_github_url() -- accepts https/http, .git suffix, trailing slash, "
        "www. host.",
        "Enforces real GitHub owner/repo naming rules (owner: alnum/hyphen, no leading/trailing hyphen, "
        "<=39 chars; repo: alnum/./_/-, <=100 chars, rejects '.', '..', '.git').",
        "Rejects: wrong scheme, missing host, embedded credentials, path traversal ('..', '%2e%2e', "
        "backslashes), control/CRLF characters, lookalike hosts (github.evil.com, github.com.evil.com), "
        "overlong input (>2048 chars).",
    ],
    deliverables=["app/domain/github_url.py; tests/test_github_url.py (34 tests incl. a security matrix)."],
    exit_criteria="57/57 tests passing overall. Every rejection path returns InvalidRepositoryUrlError or "
                  "UnsupportedRepositoryProviderError, never a raw exception.",
)

story.append(PageBreak())

# ---- Phases: pending (condensed) ----
story.append(Paragraph("Remaining Phases (5-16)", styles["H2"]))
story.append(Paragraph(
    "Unchanged in substance from the original plan; reproduced here at slightly condensed length now that "
    "the domain layer they build on already exists as real, tested code (app/domain/*).",
    styles["BodyText2"]))
story.append(Spacer(1, 8))

story += phase_block(
    5, "GitHub API Client", "PENDING",
    "Centralize every GitHub HTTP call behind one client (app/services/github_client.py) implementing "
    "RepositoryProvider's data-fetch methods against the real GitHub REST API.",
    tasks=[
        "GET /repos/{owner}/{repo}, /branches, /commits, /commits/{sha}, /languages via httpx.",
        "Timeouts (github_request_timeout_seconds), bounded retries (github_max_retries), pagination.",
        "Rate-limit detection (X-RateLimit-* headers) -> RateLimitExceededError.",
        "Optional Authorization header from settings.github_token; never logged.",
        "Wrap all raw httpx/GitHub exceptions into app.domain.errors types before they leave the client.",
    ],
    deliverables=["app/services/github_client.py; GitHubProvider registered for github.com."],
    exit_criteria="Mocked-response tests (respx) cover 200/404/401/403/429/timeout/malformed/pagination; zero "
                  "raw GitHub HTTP calls exist outside this module.",
)

story += phase_block(
    6, "Metadata and Branch Retrieval", "PENDING",
    "Use GitHubProvider to populate real repository metadata, branch list, default-branch resolution, and "
    "bounded commit history for a real public repository.",
    tasks=[
        "GitHubProvider.fetch_metadata/list_branches/get_commit_history implemented against the live API.",
        "Default-branch fallback when caller omits a branch; BranchNotFoundError when an invalid branch is "
        "requested.",
    ],
    deliverables=["Integration-style tests against a small real public repo (network-gated, skippable)."],
    exit_criteria="A real public repository URL returns accurate metadata/branches/history end-to-end.",
)

story += phase_block(
    7, "Secure Repository Cloning", "PENDING",
    "Clone real source into workspace_root/{repository_id}/source using argument-list subprocess calls "
    "only, with timeout and size limits from Settings.",
    tasks=[
        "Isolated per-repository workspace directory; no execution of repository code (no setup.py, no "
        "install scripts).",
        "Enforce clone_timeout_seconds and max_repository_size_mb; verify HEAD/branch/non-empty post-clone.",
        "Safe cleanup on failure; path-traversal-proof workspace path construction.",
    ],
    deliverables=["app/services/clone_service.py."],
    exit_criteria="Shell-injection and oversized-repo security tests pass; commit SHA is verifiably correct "
                  "for the checked-out branch.",
)

story += phase_block(
    8, "RepositoryContext Construction", "PENDING",
    "Turn API metadata + the cloned tree into a fully populated RepositoryContext: file inventory, "
    "language detection, test-framework detection, and Git evolution signals (churn, co-change).",
    tasks=[
        "File scan respecting .gitignore, excluding .git/node_modules/venvs/caches/binaries/oversized files.",
        "Language detection via extension + GitHub languages + dependency files.",
        "Test framework detection (pytest/unittest/tox/nox, Jest/Vitest/Mocha) -- no command execution.",
        "Churn/co-change calculation from git_history feeding the future Risk Engine.",
    ],
    deliverables=["Populated RepositoryContext for a real repo; unit tests against fixture commit history."],
    exit_criteria="RepositoryContext for a real public repo has non-empty file_tree, languages, and "
                  "evolution signals.",
)

story += phase_block(
    9, "Database Persistence", "PENDING",
    "Persist Repository/Branch/AnalysisRun using the existing SQLAlchemy Base and the state machine already "
    "implemented in Phase 3.",
    tasks=[
        "Provision Postgres (or SQLite for early dev) -- resolves the risk flagged in the Phase 1 audit.",
        "alembic init; first migration for Repository/Branch/AnalysisRun tables.",
        "Persist structured errors against AnalysisRun; enforce the same ALLOWED_TRANSITIONS at the DB layer.",
    ],
    deliverables=["app/models/*, alembic/ migrations."],
    exit_criteria="A completed ingestion is fully persisted and re-readable with full repository/branch/"
                  "commit/run lineage.",
)

story += phase_block(
    10, "REST API Layer", "PENDING",
    "Extend the existing api_router (app/api/v1/router.py) with the ingestion and browsing endpoints.",
    tasks=[
        "POST /api/v1/repositories/github, GET /repositories, GET /repositories/{id}, /branches, /profile, "
        "/commits, POST /repositories/{id}/refresh.",
        "Pydantic request/response models; structured error responses; pagination.",
    ],
    deliverables=["app/api/v1/repositories.py."],
    exit_criteria="Full API test suite passes: valid ingestion, invalid URL, branch selection, profile, "
                  "refresh, status polling, pagination.",
)

story += phase_block(
    11, "Asynchronous Status Tracking", "PENDING",
    "Background execution of ingestion so requests don't block, with status reflecting real stage "
    "transitions (reusing IngestionStatus from Phase 3).",
    tasks=["Background worker/task wired to the Phase 9 state machine.",
           "Status endpoint reflects live state; failures surface FAILED with the structured error."],
    deliverables=["Ingestion orchestration service."],
    exit_criteria="Frontend can poll real, monotonically progressing status for an in-flight ingestion.",
)

story += phase_block(
    12, "Downstream Analysis Hookup", "PENDING",
    "Feed the completed RepositoryContext into Repository Intelligence / Evolution / Risk / Test Planning "
    "without re-deriving repository facts.",
    tasks=["Downstream entry points accept RepositoryContext as sole repository input.",
           "Integration test: one commit SHA flows unchanged through every downstream stage."],
    deliverables=["Downstream module wiring."],
    exit_criteria="Single ingestion run produces one RepositoryContext consumed identically by every stage.",
)

story += phase_block(
    13, "Dashboard Integration", "PENDING",
    "Replace the Phase 0 connectivity-check UI with the real onboarding flow: paste URL, pick branch, "
    "watch real progress, view the profile.",
    tasks=["Repository onboarding page wired to Phase 10 endpoints.",
           "Real progress bar driven by the Phase 11 status endpoint, no simulated progress."],
    deliverables=["frontend onboarding screen/components."],
    exit_criteria="Full onboarding flow completed in-browser using only real API data.",
)

story += phase_block(
    14, "Excel Reporting", "PENDING",
    "Route repository facts into Excel export using the same models as the API/dashboard.",
    tasks=["Repository URL, provider, owner, name, branch, commit SHA, languages, timestamp added to sheet.",
           "Snapshot test asserting no secret-like values in generated workbook."],
    deliverables=["Excel export update."],
    exit_criteria="Generated Excel for a completed run has accurate repo facts, zero credential leakage.",
)

story += phase_block(
    15, "Comprehensive Test Suite", "PENDING",
    "Reach full coverage: unit, API-client, git-integration, API, and security dimensions; offline-safe by "
    "default with an opt-in network tier.",
    tasks=["Git integration tests against temporary local repos.",
           "Full security matrix: injection, traversal, oversized repos, token-leakage across logs/errors/"
           "responses/reports."],
    deliverables=["CI-runnable full suite."],
    exit_criteria="Entire suite green offline; network-tier green when enabled; no credentials in any output.",
)

story += phase_block(
    16, "End-to-End Validation", "PENDING",
    "Prove the complete pipeline for a real user with a real public repository, exactly as specified in the "
    "original plan's completion requirements.",
    tasks=["Full walk: URL -> validate -> metadata/branches -> clone -> commit SHA -> scan -> "
           "RepositoryContext -> persist -> API -> dashboard -> downstream analysis.",
           "Finalize docs/GITHUB_INTEGRATION.md and README with real usage instructions."],
    deliverables=["Signed-off demo run; finalized docs."],
    exit_criteria="A real public GitHub repository genuinely enters and completes the AURA-X pipeline "
                  "end-to-end with no mocked step.",
)

story.append(Spacer(1, 10))
story.append(Paragraph(
    "This document tracks living project status. Regenerate it "
    "(python docs/generate_project_status_plan_pdf.py) after completing each further phase.",
    styles["BodyText2"]))

doc.build(story)
print("Wrote", OUT)

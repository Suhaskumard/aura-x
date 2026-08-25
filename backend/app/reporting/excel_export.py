"""
Excel export (Phase 14): builds a workbook of repository facts for one
completed AnalysisRun.

Sourced ONLY from the Repository/AnalysisRun ORM rows -- the exact same
models and the exact same app.db.repository_dao read functions the REST
API layer (Phase 10) uses -- never RepositoryContext, never a fresh
GitHub API call, and never app.core.config.Settings (where GITHUB_TOKEN
lives). This isn't a separate data path; it's the same persisted facts,
rendered differently. `_identity_rows()` below is a closed, explicit list
of exactly what goes in the workbook -- deliberately not "dump every
column" -- so nothing beyond what the plan asks for (and nothing secret)
can end up in a generated file. See tests/test_excel_export.py for the
credential-leakage check this is designed to pass structurally, not just
by omission.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from app.db.repository_dao import get_analysis_run, get_repository_by_id
from app.domain.errors import AnalysisNotReadyError, RepositoryNotFoundError
from app.domain.repository_context import IngestionStatus
from app.models.analysis_run import AnalysisRun
from app.models.repository import Repository

_HEADER_FONT = Font(bold=True)
_REPOSITORY_SHEET_NAME = "Repository"
_LANGUAGES_SHEET_NAME = "Languages"


def _identity_rows(repository: Repository, run: AnalysisRun) -> list[tuple[str, object]]:
    profile = run.result_profile or {}
    file_inventory = profile.get("file_inventory") or {}
    git_history_summary = profile.get("git_history_summary") or {}

    # Exactly the fields the plan lists (repository URL, provider, owner,
    # repository name, selected branch, commit SHA, primary language,
    # language distribution [its own sheet, see below], analysis
    # timestamp), plus a few more identity/statistics fields already
    # sitting on these same two rows -- still nothing beyond
    # Repository/AnalysisRun columns and the already-computed profile.
    return [
        ("Repository URL", repository.source_url),
        ("Provider", repository.provider),
        ("Owner", repository.owner),
        ("Repository Name", repository.name),
        ("Selected Branch", run.branch_name),
        ("Commit SHA", run.commit_sha),
        ("Primary Language", repository.primary_language),
        ("Analysis Timestamp", run.completed_at.isoformat() if run.completed_at else None),
        ("Status", run.status),
        ("Description", repository.description),
        ("Visibility", repository.visibility),
        ("Stargazers", repository.stargazers_count),
        ("Forks", repository.forks_count),
        ("Total Files", file_inventory.get("total_files")),
        ("Total Size (bytes)", file_inventory.get("total_size_bytes")),
        ("Commits Analyzed", git_history_summary.get("commit_count")),
        ("Analysis Run ID", run.id),
    ]


def _write_identity_sheet(sheet: Worksheet, repository: Repository, run: AnalysisRun) -> None:
    sheet.title = _REPOSITORY_SHEET_NAME
    sheet.append(["Field", "Value"])
    for cell in sheet[1]:
        cell.font = _HEADER_FONT
    for field, value in _identity_rows(repository, run):
        sheet.append([field, value])
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 60


def _write_languages_sheet(sheet: Worksheet, run: AnalysisRun) -> None:
    sheet.title = _LANGUAGES_SHEET_NAME
    sheet.append(["Language", "Bytes", "Percentage"])
    for cell in sheet[1]:
        cell.font = _HEADER_FONT

    languages: dict[str, int] = (run.result_profile or {}).get("languages") or {}
    total_bytes = sum(languages.values())
    for language, byte_count in sorted(languages.items(), key=lambda kv: (-kv[1], kv[0])):
        percentage = round(100 * byte_count / total_bytes, 2) if total_bytes else 0.0
        sheet.append([language, byte_count, percentage])

    sheet.column_dimensions["A"].width = 20
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 12


def build_repository_workbook(db: Session, *, repository_id: str, analysis_run_id: str) -> Workbook:
    """Build (in memory) a workbook of repository facts for one completed
    AnalysisRun. Raises RepositoryNotFoundError if the repository or run
    doesn't exist (or the run doesn't belong to that repository), and
    AnalysisNotReadyError if the run hasn't reached READY -- there's no
    result_profile (languages, file inventory, ...) to report before then.
    """
    repository = get_repository_by_id(db, repository_id)
    if repository is None:
        raise RepositoryNotFoundError(f"No repository with id {repository_id!r}")

    run = get_analysis_run(db, analysis_run_id)
    if run is None or run.repository_id != repository_id:
        raise RepositoryNotFoundError(
            f"No analysis run {analysis_run_id!r} for repository {repository_id!r}"
        )
    if run.status != IngestionStatus.READY.value:
        raise AnalysisNotReadyError(
            f"Analysis run {analysis_run_id!r} is not READY (status={run.status}); nothing to export yet"
        )

    workbook = Workbook()
    _write_identity_sheet(workbook.active, repository, run)
    _write_languages_sheet(workbook.create_sheet(), run)
    return workbook


def save_repository_workbook(
    db: Session, *, repository_id: str, analysis_run_id: str, path: str
) -> None:
    """Build and save the workbook to `path` (an .xlsx file)."""
    workbook = build_repository_workbook(db, repository_id=repository_id, analysis_run_id=analysis_run_id)
    workbook.save(path)

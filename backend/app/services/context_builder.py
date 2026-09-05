"""
Phase 12: downstream analysis hookup.

build_repository_context() is the literal "downstream entry points accept
RepositoryContext as sole repository input" contract from the project
plan: a future Repository Intelligence / Evolution Analysis / Risk Engine
/ Test Planning module (none of which exist in this codebase -- they are
future AURA-X subsystems outside this ingestion system's scope) calls
this one function and gets everything it needs, reconstructed entirely
from persisted state. It never re-derives facts by re-calling GitHub, git,
or the scanner.

Two fields are deliberately NOT persisted and are left at their defaults:
- `local_path` IS reconstructed, since it's deterministic from
  repository_id + settings (see clone_service.workspace_dir_for) rather
  than needing its own column.
- `git_history` is left empty. Commit history is available live via
  GitHubProvider.get_commit_history() / GET /repositories/{id}/commits;
  embedding it here would mean either persisting a third growing dataset
  or an expensive rebuild-time GitHub API call, neither of which this
  contract-only phase adds.
- `metadata.topics` is left empty: Repository never gained a topics
  column (Phase 9's schema doesn't have one) -- a pre-existing, documented
  gap, not something this phase introduces.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.domain.errors import RepositoryNotFoundError
from app.domain.models import BranchInfo, EvolutionSignals, FileEntry, RepositoryMetadata
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.models.analysis_run import AnalysisRun
from app.models.branch import Branch
from app.models.repository import Repository
from app.services.clone_service import workspace_dir_for
from app.services.repository_scan_service import ScanResult


def scan_result_to_dict(scan_result: ScanResult) -> dict:
    """JSON-serializable representation of a ScanResult. Tuple keys in
    EvolutionSignals.co_change_counts can't be JSON object keys, so they're
    stored as a list of {"files": [a, b], "count": n} entries instead."""
    signals = scan_result.evolution_signals
    return {
        "file_tree": [
            {
                "relative_path": f.relative_path,
                "extension": f.extension,
                "size_bytes": f.size_bytes,
                "category": f.category,
                "language": f.language,
            }
            for f in scan_result.file_tree
        ],
        "languages": dict(scan_result.languages),
        "test_frameworks": list(scan_result.test_frameworks),
        "evolution_signals": {
            "commits_analyzed": signals.commits_analyzed,
            "file_churn": dict(signals.file_churn),
            "co_change_counts": [
                {"files": list(pair), "count": count} for pair, count in signals.co_change_counts.items()
            ],
        },
    }


def _file_tree_from_dicts(entries: list[dict]) -> list[FileEntry]:
    return [
        FileEntry(
            relative_path=e["relative_path"],
            extension=e["extension"],
            size_bytes=e["size_bytes"],
            category=e["category"],
            language=e.get("language"),
        )
        for e in entries
    ]


def _evolution_signals_from_dict(data: dict) -> EvolutionSignals:
    return EvolutionSignals(
        commits_analyzed=data["commits_analyzed"],
        file_churn=dict(data.get("file_churn", {})),
        co_change_counts={
            tuple(entry["files"]): entry["count"] for entry in data.get("co_change_counts", [])
        },
    )


def build_repository_context(
    session: Session, *, run_id: int, settings: Settings | None = None
) -> RepositoryContext:
    settings = settings or get_settings()

    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise RepositoryNotFoundError(f"AnalysisRun '{run_id}' not found")

    repository = session.get(Repository, run.repository_id)
    if repository is None:
        raise RepositoryNotFoundError(f"Repository '{run.repository_id}' not found")

    branch_rows = session.query(Branch).filter(Branch.repository_id == repository.id).all()
    branches = [
        BranchInfo(name=b.name, head_commit_sha=b.head_commit_sha, is_default=b.is_default)
        for b in branch_rows
    ]
    selected_branch = None
    if run.branch_id is not None:
        selected = next((b for b in branch_rows if b.id == run.branch_id), None)
        selected_branch = selected.name if selected else None

    metadata = RepositoryMetadata(
        repository_id=repository.id,
        name=repository.name,
        owner=repository.owner,
        description=repository.description,
        default_branch=repository.default_branch or "",
        visibility=repository.visibility,
        primary_language=repository.primary_language,
        license_name=repository.license_name,
        stargazers_count=repository.stargazers_count,
        forks_count=repository.forks_count,
        open_issues_count=repository.open_issues_count,
        created_at=repository.created_at,
        updated_at=repository.updated_at,
    )

    file_tree: list[FileEntry] = []
    languages: dict[str, int] = {}
    test_frameworks: list[str] = []
    evolution_signals: EvolutionSignals | None = None
    if run.scan_result is not None:
        file_tree = _file_tree_from_dicts(run.scan_result.get("file_tree", []))
        languages = dict(run.scan_result.get("languages", {}))
        test_frameworks = list(run.scan_result.get("test_frameworks", []))
        evolution_signals = _evolution_signals_from_dict(run.scan_result.get("evolution_signals", {}))

    local_path = None
    if run.status not in (IngestionStatus.PENDING.value, IngestionStatus.VALIDATING.value):
        # Deterministic from repository_id + settings -- never persisted
        # separately. Only meaningful once cloning has actually started.
        local_path = str(workspace_dir_for(repository.id, settings))

    return RepositoryContext(
        repository_id=repository.id,
        provider=repository.provider,
        source_url=repository.source_url,
        owner=repository.owner,
        repository_name=repository.name,
        local_path=local_path,
        selected_branch=selected_branch,
        default_branch=repository.default_branch,
        commit_sha=run.commit_sha,
        metadata=metadata,
        branches=branches,
        languages=languages,
        file_tree=file_tree,
        git_history=[],
        test_frameworks=test_frameworks,
        evolution_signals=evolution_signals,
        analysis_status=IngestionStatus(run.status),
        last_error=run.last_error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )

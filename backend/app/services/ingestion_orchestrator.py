"""
End-to-end ingestion orchestration (Phase 10): URL -> validate -> fetch
metadata -> resolve branch -> fetch commit history -> clone -> scan/detect
(Phase 8) -> persist (Phase 9). This is what the REST API layer
(app/api/v1/routes/repositories.py) calls; it's synchronous for now --
Phase 11 moves it to a background job without changing this function's
contract.

A malformed/unsupported URL fails fast with nothing persisted (there's no
valid owner/repo to record yet). Once a RepositoryContext exists (URL
parsed successfully), any failure is captured onto it and still persisted
as a FAILED AnalysisRun -- see docs/GITHUB_INTEGRATION.md "Database
Persistence" for why that's diagnosable rather than a silent 500.
"""

from __future__ import annotations

from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.repository_dao import get_repository_by_id
from app.domain.errors import (
    RepositoryIntegrationError,
    RepositoryNotFoundError,
    UnsupportedRepositoryProviderError,
)
from app.domain.github_url import parse_github_url
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.domain.repository_provider import get_provider_class_for_host
from app.models.analysis_run import AnalysisRun
from app.services.ingestion_persistence import build_config_snapshot, persist_repository_context
from app.services.repository_service import (
    DEFAULT_EVOLUTION_COMMIT_LIMIT,
    assemble_repository_context,
    build_clone_target_dir,
    select_branch,
)

# This module lives inside the app.services package, so importing it
# already runs app/services/__init__.py first, which registers
# GitHubProvider (and any future provider) against
# app.domain.repository_provider -- get_provider_class_for_host() below
# always sees it.


def ingest_github_repository(
    db: Session,
    settings: Settings,
    *,
    repository_url: str,
    branch: str | None,
    evolution_commit_limit: int = DEFAULT_EVOLUTION_COMMIT_LIMIT,
) -> AnalysisRun:
    """Run the full ingestion pipeline for `repository_url` and persist the
    result. Returns the persisted AnalysisRun (READY or FAILED)."""
    parsed = parse_github_url(repository_url)  # raises before anything is persisted
    provider_cls = get_provider_class_for_host(urlparse(parsed.normalized_url).hostname or "")
    if provider_cls is None:  # pragma: no cover - parse_github_url already restricts the host set
        raise UnsupportedRepositoryProviderError(f"No provider registered for {parsed.normalized_url}")

    context = RepositoryContext(
        repository_id=str(uuid4()),
        provider=provider_cls.name,
        source_url=parsed.normalized_url,
        owner=parsed.owner,
        repository_name=parsed.repository,
    )
    context.transition_to(IngestionStatus.VALIDATING)

    provider = provider_cls(settings=settings)
    try:
        context.transition_to(IngestionStatus.FETCHING_METADATA)
        context.metadata = provider.fetch_metadata(context.owner, context.repository_name)
        context.default_branch = context.metadata.default_branch

        context.transition_to(IngestionStatus.FETCHING_BRANCHES)
        context.branches = provider.list_branches(context.owner, context.repository_name)
        selected = select_branch(context.branches, branch)
        context.selected_branch = selected.name
        context.git_history = provider.get_commit_history(
            context.owner, context.repository_name, selected.name, limit=settings.max_commit_history
        )
        context.languages = provider.get_languages(context.owner, context.repository_name)

        context.transition_to(IngestionStatus.CLONING)
        target_dir = build_clone_target_dir(settings, context.owner, context.repository_name)
        clone_result = provider.clone(context.owner, context.repository_name, selected.name, target_dir)
        context.local_path = clone_result.local_path
        context.commit_sha = clone_result.commit_sha

        assemble_repository_context(context, provider=provider, evolution_commit_limit=evolution_commit_limit)
    except RepositoryIntegrationError as exc:
        context.fail(exc.to_dict())
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()

    config_snapshot = build_config_snapshot(settings, evolution_commit_limit=evolution_commit_limit)
    return persist_repository_context(db, context, config_snapshot=config_snapshot)


def refresh_repository_ingestion(
    db: Session,
    settings: Settings,
    *,
    repository_id: str,
    branch: str | None,
    evolution_commit_limit: int = DEFAULT_EVOLUTION_COMMIT_LIMIT,
) -> AnalysisRun:
    """Re-run ingestion for an already-known repository, using its stored
    source_url. Adds a new AnalysisRun to the same Repository row rather
    than creating a duplicate -- see upsert_repository()."""
    repository = get_repository_by_id(db, repository_id)
    if repository is None:
        raise RepositoryNotFoundError(f"No repository with id {repository_id!r}")

    return ingest_github_repository(
        db,
        settings,
        repository_url=repository.source_url,
        branch=branch,
        evolution_commit_limit=evolution_commit_limit,
    )

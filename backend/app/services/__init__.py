"""
Application services: GitHub API client, provider implementations, clone
service (Phase 7), ingestion orchestration (Phase 11).

Importing this package registers every concrete RepositoryProvider
(currently GitHubProvider for github.com) against
app.domain.repository_provider's registry, so callers can resolve a
provider by hostname without importing the concrete class directly.
"""

from app.services import github_provider  # noqa: F401  (registers GitHubProvider)

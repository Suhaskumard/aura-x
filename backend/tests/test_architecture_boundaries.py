"""
Phase 2 (integration architecture) and Phase 10 (REST API) boundary checks.

These are regression guards, not feature tests: they pin today's actual
surface area so that adding a new route, or a new GitHub-specific import
outside app/services, is a deliberate, visible change to this test file
rather than a silent architectural drift.
"""

from pathlib import Path

from app.main import app

APP_ROOT = Path(__file__).resolve().parent.parent / "app"


def _iter_python_files(*, exclude_dir: str):
    for path in APP_ROOT.rglob("*.py"):
        if exclude_dir in path.parts:
            continue
        yield path


def test_registered_routes_match_current_implementation():
    # Phase 10 (REST API layer) landed: /api/v1/repositories routes now
    # exist. This must be updated deliberately if a future phase adds a
    # new route.
    paths = {route.path for route in app.routes}
    assert paths == {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/api/v1/health",
        "/api/v1/repositories",
        "/api/v1/repositories/{repository_id}",
        "/api/v1/repositories/{repository_id}/branches",
        "/api/v1/repositories/{repository_id}/commits",
        "/api/v1/repositories/{repository_id}/refresh",
        "/api/v1/analysis-runs/{run_id}",
        "/api/v1/analysis-runs/{run_id}/export.xlsx",
        "/",
    }


def test_no_github_specific_types_imported_outside_services_layer():
    # Phase 2 rule: only app/services may import a concrete provider type
    # (GitHubProvider, GitHubApiClient). Domain and API layers must depend
    # only on the RepositoryProvider abstraction / RepositoryContext.
    offending = []
    for path in _iter_python_files(exclude_dir="services"):
        text = path.read_text(encoding="utf-8")
        if "GitHubProvider" in text or "GitHubApiClient" in text:
            offending.append(str(path.relative_to(APP_ROOT.parent)))
    assert offending == []


_ALLOWED_SUBPROCESS_MODULE = APP_ROOT / "services" / "clone_service.py"


def test_shell_true_never_used_anywhere_in_app():
    # Zero tolerance, no exceptions: shell=True is never acceptable, even in
    # the one module allowed to spawn a subprocess (clone_service.py uses
    # argument-list subprocess.run calls only).
    offending = []
    for path in _iter_python_files(exclude_dir="__pycache__"):
        text = path.read_text(encoding="utf-8")
        if "shell=True" in text:
            offending.append(str(path.relative_to(APP_ROOT.parent)))
    assert offending == []


def test_subprocess_usage_confined_to_clone_service():
    # Phase 7 (clone) introduced the codebase's only subprocess caller.
    # Everywhere else must stay at zero -- a new subprocess/os.system usage
    # outside clone_service.py is a deliberate, visible change to this test,
    # not a silent architectural drift.
    offending = []
    for path in _iter_python_files(exclude_dir="__pycache__"):
        if path == _ALLOWED_SUBPROCESS_MODULE:
            continue
        text = path.read_text(encoding="utf-8")
        if "os.system(" in text or "import subprocess" in text:
            offending.append(str(path.relative_to(APP_ROOT.parent)))
    assert offending == []


def test_models_module_exposes_exactly_the_phase_9_orm_classes():
    # Phase 9 (database persistence) landed: app/models/__init__.py now
    # exports exactly Repository/Branch/AnalysisRun. This must be updated
    # deliberately if a future phase adds/removes a model.
    import app.models as models_module

    assert set(models_module.__all__) == {"Repository", "Branch", "AnalysisRun"}


def test_db_base_has_exactly_the_phase_9_registered_models():
    import app.models  # noqa: F401  (registers the three model classes)
    from app.db.base import Base

    mapped_class_names = {mapper.class_.__name__ for mapper in Base.registry.mappers}
    assert mapped_class_names == {"Repository", "Branch", "AnalysisRun"}

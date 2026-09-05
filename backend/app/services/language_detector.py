"""
Language detection for scanned files.

Per-file language is always derived locally from the extension table
below. The aggregate RepositoryContext.languages (bytes per language)
prefers the already-fetched GitHub API result (Phase 6,
GitHubProvider.get_languages) as authoritative, since it matches GitHub's
own linguist analysis -- falling back to local per-file byte totals only
when the API result is empty/unavailable.

Caveat: GitHub's /languages endpoint reflects whichever ref its linguist
analysis targeted, which may not be byte-identical to the exact
commit_sha actually checked out locally. This is an expected
approximation, not a bug to "fix" later.
"""

from __future__ import annotations

_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".php": "PHP",
    ".cs": "C#",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
}


def detect_language(extension: str) -> str | None:
    return _EXTENSION_LANGUAGE_MAP.get(extension.lower())


def resolve_languages(
    *, local_scan_totals: dict[str, int], github_languages: dict[str, int]
) -> dict[str, int]:
    if github_languages:
        return dict(github_languages)
    return dict(local_scan_totals)

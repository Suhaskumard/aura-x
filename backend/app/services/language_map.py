"""
Shared extension/manifest -> language name tables used by both
file_scanner.py (per-file FileEntry.language) and language_detector.py
(repository-level aggregation). Kept separate so neither module has to
import the other.
"""

from __future__ import annotations

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hxx": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".m": "Objective-C",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "Less",
    ".sql": "SQL",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".xml": "XML",
    ".vue": "Vue",
    ".dart": "Dart",
    ".lua": "Lua",
    ".r": "R",
}

# Dependency/build manifest filename -> the language it signals, used as a
# fallback when a repository's primary code hasn't been scanned yet or the
# GitHub languages API returned nothing (e.g. a mostly-empty new repo).
DEPENDENCY_FILE_LANGUAGE_MAP: dict[str, str] = {
    "requirements.txt": "Python",
    "requirements-dev.txt": "Python",
    "Pipfile": "Python",
    "pyproject.toml": "Python",
    "setup.py": "Python",
    "setup.cfg": "Python",
    "package.json": "JavaScript",
    "tsconfig.json": "TypeScript",
    "pom.xml": "Java",
    "build.gradle": "Java",
    "build.gradle.kts": "Kotlin",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "CMakeLists.txt": "C++",
}

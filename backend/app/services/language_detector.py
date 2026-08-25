"""
Language detection (Phase 8): reconciles GitHub's reported byte-count
languages with what the scanned working tree actually contains, so
languages are still reported for a provider with no language API (e.g. a
future LocalRepositoryProvider) or when GitHub's linguist data is thin
(a repo with only a README returns {} from the languages API).
"""

from __future__ import annotations

from app.domain.models import FileEntry
from app.services.language_map import DEPENDENCY_FILE_LANGUAGE_MAP, EXTENSION_LANGUAGE_MAP


def detect_languages(
    file_tree: list[FileEntry], github_languages: dict[str, int] | None = None
) -> dict[str, int]:
    """Merge provider-reported language byte counts with extension- and
    dependency-manifest-based detection from `file_tree`.

    GitHub's counts (when present) are authoritative and used as the
    starting point; each scanned source file then adds its size to its
    detected language's total. A dependency/build manifest (requirements.txt,
    package.json, ...) that implies a language absent from the tally is
    added with a zero count, so e.g. a pure-config Python repo still
    reports "Python" even if no .py file happened to be scanned. Returned
    dict is sorted by descending byte count.
    """
    counts: dict[str, int] = dict(github_languages or {})

    for entry in file_tree:
        language = entry.language or EXTENSION_LANGUAGE_MAP.get(entry.extension)
        if language is None:
            continue
        counts[language] = counts.get(language, 0) + entry.size_bytes

    for entry in file_tree:
        filename = entry.relative_path.rsplit("/", 1)[-1]
        language = DEPENDENCY_FILE_LANGUAGE_MAP.get(filename)
        if language and language not in counts:
            counts[language] = 0

    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

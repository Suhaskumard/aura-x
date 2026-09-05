import pytest

from app.services.language_detector import detect_language, resolve_languages


@pytest.mark.parametrize(
    "extension,expected",
    [
        (".py", "Python"),
        (".PY", "Python"),
        (".ts", "TypeScript"),
        (".tsx", "TypeScript"),
        (".js", "JavaScript"),
        (".rs", "Rust"),
        (".go", "Go"),
        (".unknownext", None),
        ("", None),
    ],
)
def test_detect_language(extension, expected):
    assert detect_language(extension) == expected


def test_resolve_languages_prefers_github_when_present():
    result = resolve_languages(
        local_scan_totals={"Python": 999},
        github_languages={"Python": 1234, "HTML": 56},
    )
    assert result == {"Python": 1234, "HTML": 56}


def test_resolve_languages_falls_back_to_local_when_github_empty():
    result = resolve_languages(local_scan_totals={"Python": 999}, github_languages={})
    assert result == {"Python": 999}


def test_resolve_languages_returns_copy_not_original_dict():
    github_languages = {"Python": 1}
    result = resolve_languages(local_scan_totals={}, github_languages=github_languages)
    result["Python"] = 999
    assert github_languages["Python"] == 1

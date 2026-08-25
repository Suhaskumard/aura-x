import json

from app.services.dependency_scanner import extract_dependencies


def test_extracts_names_from_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "fastapi==0.115.6\n# a comment\n\nhttpx>=0.28,<1\n-e ./local-pkg\npydantic~=2.10\n",
        encoding="utf-8",
    )
    deps = extract_dependencies(tmp_path)
    assert deps == ["fastapi", "httpx", "pydantic"]


def test_extracts_names_from_package_json(tmp_path):
    payload = {"dependencies": {"react": "^18.0.0"}, "devDependencies": {"vitest": "^1.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    deps = extract_dependencies(tmp_path)
    assert deps == ["react", "vitest"]


def test_merges_multiple_manifests(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "1"}}), encoding="utf-8")
    deps = extract_dependencies(tmp_path)
    assert deps == ["fastapi", "react"]


def test_no_manifests_returns_empty_list(tmp_path):
    assert extract_dependencies(tmp_path) == []


def test_malformed_package_json_does_not_raise(tmp_path):
    (tmp_path / "package.json").write_text("{broken", encoding="utf-8")
    assert extract_dependencies(tmp_path) == []

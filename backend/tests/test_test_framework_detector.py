import json
from pathlib import Path

from app.domain.models import FileEntry
from app.services.test_framework_detector import detect_test_directories, detect_test_frameworks


def entry(path: str) -> FileEntry:
    extension = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    return FileEntry(relative_path=path, extension=extension, size_bytes=1, category="test")


def test_detects_pytest_from_conftest(tmp_path):
    file_tree = [entry("tests/conftest.py")]
    frameworks = detect_test_frameworks(tmp_path, file_tree)
    assert frameworks == ["pytest"]


def test_detects_pytest_from_ini_file(tmp_path):
    file_tree = [entry("pytest.ini")]
    frameworks = detect_test_frameworks(tmp_path, file_tree)
    assert frameworks == ["pytest"]


def test_detects_tox_and_nox(tmp_path):
    file_tree = [entry("tox.ini"), entry("noxfile.py")]
    frameworks = detect_test_frameworks(tmp_path, file_tree)
    assert frameworks == ["nox", "tox"]


def test_detects_pytest_declared_in_requirements(tmp_path):
    (tmp_path / "requirements-dev.txt").write_text("pytest==8.3.4\nrespx\n", encoding="utf-8")
    frameworks = detect_test_frameworks(tmp_path, [])
    assert frameworks == ["pytest"]


def test_detects_jest_from_config_file(tmp_path):
    file_tree = [entry("jest.config.js")]
    frameworks = detect_test_frameworks(tmp_path, file_tree)
    assert frameworks == ["Jest"]


def test_detects_vitest_and_mocha_from_package_json(tmp_path):
    payload = {"devDependencies": {"vitest": "^1.0.0", "mocha": "^10.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    frameworks = detect_test_frameworks(tmp_path, [])
    assert frameworks == ["Mocha", "Vitest"]


def test_no_evidence_means_no_frameworks_reported(tmp_path):
    file_tree = [entry("tests/test_something.py")]
    frameworks = detect_test_frameworks(tmp_path, file_tree)
    assert frameworks == []


def test_malformed_package_json_does_not_raise(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json", encoding="utf-8")
    frameworks = detect_test_frameworks(tmp_path, [])
    assert frameworks == []


def test_package_json_with_dependencies_as_wrong_shape_does_not_raise(tmp_path):
    # Well-formed JSON, but "devDependencies" isn't the {name: version}
    # object npm's schema requires (a hand-edited/corrupted manifest) --
    # must be skipped, not crash the whole detection pass.
    payload = {"devDependencies": ["jest"]}
    (tmp_path / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    frameworks = detect_test_frameworks(tmp_path, [])
    assert frameworks == []


def test_detect_test_directories_finds_conventional_names():
    file_tree = [
        entry("tests/test_app.py"),
        entry("tests/unit/test_util.py"),
        entry("src/__tests__/component.test.js"),
        entry("app/main.py"),
    ]
    directories = detect_test_directories(file_tree)
    assert directories == ["src/__tests__", "tests"]

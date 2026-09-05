from pathlib import Path

from app.core.config import Settings
from app.services.file_scanner import scan_file_tree
from app.services.test_framework_detector import detect_test_frameworks


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _scan(repo: Path):
    return scan_file_tree(repo, Settings(workspace_root=repo.parent / "workspace"))


def test_detects_pytest_via_ini_presence(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "pytest.ini", "[pytest]\n")
    assert detect_test_frameworks(repo, _scan(repo)) == ["pytest"]


def test_detects_pytest_via_pyproject_section(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-q'\n")
    assert "pytest" in detect_test_frameworks(repo, _scan(repo))


def test_detects_pytest_via_requirements(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "requirements-dev.txt", "pytest==8.0.0\n")
    assert "pytest" in detect_test_frameworks(repo, _scan(repo))


def test_detects_tox(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "tox.ini", "[tox]\nenvlist = py311\n")
    assert "tox" in detect_test_frameworks(repo, _scan(repo))


def test_detects_nox(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "noxfile.py", "import nox\n")
    assert "nox" in detect_test_frameworks(repo, _scan(repo))


def test_detects_jest_via_config_file(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "jest.config.js", "module.exports = {}\n")
    assert "jest" in detect_test_frameworks(repo, _scan(repo))


def test_detects_jest_via_package_json(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "package.json", '{"devDependencies": {"jest": "^29.0.0"}}\n')
    assert "jest" in detect_test_frameworks(repo, _scan(repo))


def test_detects_vitest(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "vitest.config.ts", "export default {}\n")
    assert "vitest" in detect_test_frameworks(repo, _scan(repo))


def test_detects_mocha(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / ".mocharc.json", "{}\n")
    assert "mocha" in detect_test_frameworks(repo, _scan(repo))


def test_detects_unittest_from_test_file_import(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "tests" / "test_foo.py", "import unittest\n\nclass T(unittest.TestCase):\n    pass\n")
    assert "unittest" in detect_test_frameworks(repo, _scan(repo))


def test_no_frameworks_detected_in_plain_repo(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "main.py", "print('hello')\n")
    assert detect_test_frameworks(repo, _scan(repo)) == []


def test_multiple_frameworks_detected_simultaneously(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "tox.ini", "[tox]\n")
    _write(repo / "package.json", '{"devDependencies": {"jest": "1.0.0", "mocha": "1.0.0"}}\n')
    detected = detect_test_frameworks(repo, _scan(repo))
    assert detected == sorted({"tox", "jest", "mocha"})


def test_never_executes_anything():
    import app.services.test_framework_detector as module
    import inspect

    source = inspect.getsource(module)
    assert "import subprocess" not in source
    assert "os.system(" not in source

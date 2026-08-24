"""M2: harness init core (guide sections 8-12, 25-26)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from harness.init import (  # noqa: E402
    REQUIRED_FILES,
    init_harness,
)
from harness.templates import TemplateNotFoundError, templates_dir  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_creates_harness_directory(repo):
    result = init_harness(repo)
    assert result.harness_dir == repo / ".harness"
    assert result.harness_dir.is_dir()


def test_creates_required_files(repo):
    init_harness(repo)
    for name in REQUIRED_FILES:
        assert (repo / ".harness" / name).is_file(), name


def test_creates_findings_and_evidence_dirs(repo):
    init_harness(repo)
    assert (repo / ".harness" / "findings").is_dir()
    assert (repo / ".harness" / "evidence").is_dir()


def test_files_match_templates(repo):
    init_harness(repo)
    for name in REQUIRED_FILES:
        produced = (repo / ".harness" / name).read_text(encoding="utf-8")
        source = (templates_dir() / name).read_text(encoding="utf-8")
        assert produced == source, name


def test_is_idempotent(repo):
    first = init_harness(repo)
    second = init_harness(repo)
    assert first.created and not second.created
    assert sorted(p.name for p in second.skipped) == sorted(REQUIRED_FILES)


def test_does_not_overwrite_modified_current_task(repo):
    init_harness(repo)
    target = repo / ".harness" / "current-task.yaml"
    target.write_text("state: VERIFYING\n# human edit\n", encoding="utf-8")
    init_harness(repo)
    assert target.read_text(encoding="utf-8") == \
        "state: VERIFYING\n# human edit\n"


def test_does_not_overwrite_existing_gate_yaml(repo):
    init_harness(repo)
    target = repo / ".harness" / "gate.yaml"
    target.write_text("gate: {}\n", encoding="utf-8")
    init_harness(repo)
    assert target.read_text(encoding="utf-8") == "gate: {}\n"


def test_completes_partially_initialized_harness(repo):
    h = repo / ".harness"
    h.mkdir()
    (h / "findings").mkdir()
    (h / "current-task.yaml").write_text("state: CREATED\n",
                                         encoding="utf-8")
    result = init_harness(repo)
    assert Path(".harness/current-task.yaml") not in [
        p.relative_to(repo) for p in result.created]
    # missing files filled in, existing content preserved
    assert (h / "current-task.yaml").read_text() == "state: CREATED\n"
    assert (h / "gate.yaml").exists()
    assert (h / "evidence").is_dir()


def test_fails_if_template_missing(repo, monkeypatch):
    def broken_dir():
        d = REPO / "templates"
        monkeypatch.delattr  # noqa: F841
        return d
    import harness.templates as tmod
    fake = REPO / "templates-does-not-exist"
    monkeypatch.setattr(tmod, "templates_dir", lambda: fake)
    with pytest.raises(TemplateNotFoundError):
        init_harness(repo)
    # must NOT have created empty files
    if (repo / ".harness").exists():
        assert not any(
            (repo / ".harness" / n).exists() for n in REQUIRED_FILES)


def test_result_reports_created_and_skipped(repo):
    result = init_harness(repo)
    assert len(result.created) == len(REQUIRED_FILES)
    assert result.skipped == []


def test_service_layer_inits_repo_root(tmp_path):
    from harness.init import init_current_repository

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True,
                   capture_output=True)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    result = init_current_repository(cwd=nested)
    assert result.harness_dir == tmp_path / ".harness"

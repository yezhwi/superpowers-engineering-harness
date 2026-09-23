import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-agy.sh"


def _executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def agy_environment(tmp_path):
    cwd = tmp_path / "not-a-repository"
    cwd.mkdir()
    home = tmp_path / "home"
    skills_root = home / ".gemini" / "antigravity-cli" / "skills"
    source = tmp_path / "harness-source"
    shutil.copytree(ROOT / "skills", source / "skills")
    (source / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    _executable(bin_dir / "curl", "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$AGY_TEST_LOG\"\nprintf '%s' '{\"tag_name\": \"v9.9.9\"}'\n")
    _executable(bin_dir / "git", "#!/bin/sh\nprintf 'git %s\\n' \"$*\" >> \"$AGY_TEST_LOG\"\ndest=\"\"; for arg in \"$@\"; do dest=\"$arg\"; done\ncp -R \"$AGY_TEST_SOURCE\" \"$dest\"\n")
    _executable(bin_dir / "python3", "#!/bin/sh\nif [ \"$1\" = \"-c\" ]; then exec \"$AGY_REAL_PYTHON\" \"$@\"; fi\nprintf 'python3 %s\\n' \"$*\" >> \"$AGY_TEST_LOG\"\n")
    _executable(bin_dir / "harness", "#!/bin/sh\nprintf 'harness %s\\n' \"$*\" >> \"$AGY_TEST_LOG\"\n")
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}", "AGY_TEST_LOG": str(log), "AGY_TEST_SOURCE": str(source), "AGY_REAL_PYTHON": shutil.which("python3") or shutil.which("python")}
    return cwd, skills_root, log, env


def test_installer_uses_latest_release_and_installs_global_skills(agy_environment):
    cwd, skills_root, log, env = agy_environment

    result = subprocess.run([INSTALLER], cwd=cwd, env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    assert "git clone --depth 1 --branch v9.9.9" in log.read_text()
    assert not "harness init" in log.read_text()
    assert (skills_root / "engineering-harness" / "SKILL.md").is_file()
    assert (skills_root / "quality-gate" / "SKILL.md").is_file()


def test_installer_accepts_explicit_version_without_latest_lookup(agy_environment):
    cwd, _, log, env = agy_environment

    result = subprocess.run([INSTALLER, "v0.2.9"], cwd=cwd, env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "git clone --depth 1 --branch v0.2.9" in calls
    assert not calls.startswith("-fsSL")


def test_installer_replaces_harness_skills_and_preserves_unrelated_skills(agy_environment):
    cwd, skills_root, _, env = agy_environment
    existing = skills_root / "engineering-harness"
    existing.mkdir(parents=True)
    (existing / "marker").write_text("old")
    unrelated = skills_root / "my-skill"
    unrelated.mkdir()
    (unrelated / "marker").write_text("keep")

    result = subprocess.run([INSTALLER], cwd=cwd, env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    assert not (existing / "marker").exists()
    assert (existing / "SKILL.md").is_file()
    assert (unrelated / "marker").read_text() == "keep"

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
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "harness-source"
    shutil.copytree(ROOT / "skills", source / "skills")
    (source / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    _executable(
        bin_dir / "curl",
        "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$AGY_TEST_LOG\"\nprintf '%s' '{\"tag_name\": \"v9.9.9\"}'\n",
    )
    _executable(
        bin_dir / "git",
        "#!/bin/sh\nprintf 'git %s\\n' \"$*\" >> \"$AGY_TEST_LOG\"\n"
        "dest=\"\"; for arg in \"$@\"; do dest=\"$arg\"; done\n"
        "cp -R \"$AGY_TEST_SOURCE\" \"$dest\"\n",
    )
    _executable(
        bin_dir / "python3",
        "#!/bin/sh\nif [ \"$1\" = \"-c\" ]; then exec \"$AGY_REAL_PYTHON\" \"$@\"; fi\n"
        "printf 'python3 %s\\n' \"$*\" >> \"$AGY_TEST_LOG\"\n",
    )
    _executable(
        bin_dir / "harness",
        "#!/bin/sh\nprintf 'harness %s\\n' \"$*\" >> \"$AGY_TEST_LOG\"\n",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AGY_TEST_LOG": str(log),
        "AGY_TEST_SOURCE": str(source),
        "AGY_REAL_PYTHON": shutil.which("python3") or shutil.which("python"),
    }
    return workspace, log, env


def test_installer_uses_latest_release_and_installs_all_skills(agy_environment):
    workspace, log, env = agy_environment

    result = subprocess.run([INSTALLER], cwd=workspace, env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    assert "git clone --depth 1 --branch v9.9.9" in log.read_text()
    assert "harness init" in log.read_text()
    assert (workspace / ".agents" / "skills" / "engineering-harness" / "SKILL.md").is_file()
    assert (workspace / ".agents" / "skills" / "quality-gate" / "SKILL.md").is_file()


def test_installer_accepts_explicit_version_without_latest_lookup(agy_environment):
    workspace, log, env = agy_environment

    result = subprocess.run([INSTALLER, "v0.2.9"], cwd=workspace, env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "git clone --depth 1 --branch v0.2.9" in calls
    assert not calls.startswith("-fsSL")


def test_installer_refuses_to_overwrite_existing_skill(agy_environment):
    workspace, log, env = agy_environment
    existing = workspace / ".agents" / "skills" / "engineering-harness"
    existing.mkdir(parents=True)
    (existing / "marker").write_text("keep")

    result = subprocess.run([INSTALLER], cwd=workspace, env=env, text=True, capture_output=True)

    assert result.returncode != 0
    assert "Skill exists" in result.stderr
    assert (existing / "marker").read_text() == "keep"
    assert not log.exists()

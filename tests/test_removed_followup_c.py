"""Retired public identifiers stay absent; ordinary workflow remains available."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["candidate_commit", "candidate_assessment", "candidate_runner", "git_mutation"])
def test_removed_modules_are_not_importable(name):
    assert importlib.util.find_spec(f"harness.{name}") is None


@pytest.mark.parametrize("command", ["candidate", "commit"])
def test_removed_top_level_commands_are_not_advertised_or_accepted(tmp_path, command):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-m", "harness.cli", command, "--help"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "invalid choice" in result.stderr


def test_removed_gate_option_and_package_assets_stay_absent(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-m", "harness.cli", "gate", "--help"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "--candidate" not in result.stdout
    assert not list((ROOT / "src/harness/schemas").glob("candidate-*.schema.json"))
    package = json.loads((ROOT / "package.json").read_text())
    for name in ("docs/candidate-commit.md", "docs/superpowers/specs/2026-10-21-gate-before-commit-design.md"):
        assert not (ROOT / name).exists()
        assert name not in package["files"]

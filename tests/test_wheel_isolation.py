"""Installed wheel runs without repository layout."""

import os
from pathlib import Path
import subprocess
import sys
import venv


REPO = Path(__file__).resolve().parent.parent


def _python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _harness(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/harness.exe" if os.name == "nt" else "bin/harness")


def test_wheel_runs_outside_checkout(tmp_path):
    dist = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--wheel-dir", str(dist)],
        cwd=REPO, check=True, capture_output=True, text=True,
    )
    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
    python = _python(venv_dir)
    harness = _harness(venv_dir)
    wheel = next(dist.glob("*.whl"))
    subprocess.run(
        [python, "-m", "pip", "install", str(wheel)],
        check=True, capture_output=True, text=True,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outside, check=True)
    for args in (["--help"], ["init"], ["status"]):
        result = subprocess.run(
            [harness, *args], cwd=outside,
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

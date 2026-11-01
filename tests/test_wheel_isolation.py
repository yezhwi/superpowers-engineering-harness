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
    # Source-checkout imports must not masquerade as an installed distribution.
    isolated_env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    dist = tmp_path / "dist"
    dist.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-B", "-c",
            'import harness_build_backend; harness_build_backend.build_wheel(' + repr(str(dist)) + ')',
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    venv_dir = tmp_path / "venv"
    # Reuse already available runtime dependencies; never fetch or install them.
    # The wheel itself must still load from this temporary environment, not checkout.
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
    python = _python(venv_dir)
    harness = _harness(venv_dir)
    wheel = next(dist.glob("*.whl"))
    subprocess.run(
        [python, "-m", "pip", "install", "--no-index", "--no-deps", "--ignore-installed", str(wheel)],
        env=isolated_env,
        check=True,
        capture_output=True,
        text=True,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    imported = subprocess.run(
        [python, "-c", "import harness; print(harness.__file__)"],
        cwd=outside,
        env=isolated_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(imported.stdout.strip()).is_relative_to(venv_dir)
    resources = subprocess.run(
        [python, '-c', 'from harness.schema_resources import read_schema; '
         'from harness.storage.migration import reader_identity; '
         'from pathlib import Path; '
         'assert all(read_schema(n) for n in ["storage-layout.schema.json", "storage-operation.schema.json", '
         '"storage-history.schema.json", "storage-experiment.schema.json"]); '
         'assert all(Path(v["path"]).is_relative_to(' + repr(str(venv_dir)) + ') '
         'for v in reader_identity()["modules"].values())'],
        cwd=outside, env=isolated_env, capture_output=True, text=True,
    )
    assert resources.returncode == 0, resources.stderr
    subprocess.run(["git", "init", "-q"], cwd=outside, check=True)
    for args in (["--help"], ["evidence", "--help"], ["storage", "migrate", "--help"],
                 ["init"], ["status"], ["storage", "inspect", "--json"]):
        result = subprocess.run(
            [harness, *args],
            env=isolated_env,
            cwd=outside,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        if args == ["evidence", "--help"]:
            assert "--covered-test" in result.stdout
            assert "--phase" in result.stdout

    result = subprocess.run(
        [harness, "task", "recover", "TASK-005", "--reason", "stale"],
        env=isolated_env,
        cwd=outside,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "TASK_GIT_BASELINE_REQUIRED" in result.stderr

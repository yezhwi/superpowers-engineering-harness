import subprocess
import sys
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]


def run_cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", "benchmark", "alignment", *args],
        cwd=cwd, capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src")}, check=False,
    )


def test_alignment_benchmark_cli_reports_explicit_records(tmp_path):
    records = tmp_path / "records.yaml"
    records.write_text(yaml.safe_dump({
        "tasks": [{"id": "TASK-001", "state": "DONE", "history": []}],
        "alignments": [{"task_id": "TASK-001", "open_questions": []}],
        "findings": [],
    }))

    result = run_cli(tmp_path, "--records", str(records))

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["drift"] == {"count": 0, "rate": 0.0}


def test_alignment_benchmark_cli_missing_records_are_inconclusive(tmp_path):
    records = tmp_path / "records.yaml"
    records.write_text(yaml.safe_dump({"tasks": []}))

    result = run_cli(tmp_path, "--records", str(records))

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["status"] == "INCONCLUSIVE"

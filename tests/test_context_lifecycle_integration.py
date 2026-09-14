"""Classify-to-evidence lifecycle uses fresh authoritative Context only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import test_context_builder
import yaml

from harness.context.store import load_context

REPO = Path(__file__).resolve().parents[1]
harness = test_context_builder.harness


def cli(root, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )


def test_classify_compact_stale_regenerate_and_evidence_review_input(harness):
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = "CREATED"
    task["risk"] = None
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    flags = [
        item
        for name, value in {
            "scope": "low",
            "contract": "none",
            "data": "none",
            "authorization": "none",
            "security": "none",
            "concurrency": "none",
            "deployment": "none",
        }.items()
        for item in (f"--{name}", value)
    ]

    classified = cli(harness.parent, "task", "classify", "--level", "Q1", *flags)
    assert classified.returncode == 0, classified.stderr
    compact = cli(harness.parent, "context", "--compact", "--json")
    assert compact.returncode == 0, compact.stderr
    first = json.loads(compact.stdout)
    assert first["mode"] == "compact"

    with (harness / "requirements.yaml").open("a") as stream:
        stream.write("\n# authoritative change\n")
    stale = cli(harness.parent, "context", "validate")
    assert stale.returncode == 2
    assert "CONTEXT_STALE" in stale.stderr

    regenerated = cli(harness.parent, "context", "--compact", "--json")
    assert regenerated.returncode == 0, regenerated.stderr
    current = json.loads(regenerated.stdout)
    evidence = yaml.safe_load((harness / "context/evidence.yaml").read_text())
    assert current["context_hash"] != first["context_hash"]
    assert evidence["context_hash"] == current["context_hash"]
    assert evidence["integrity"] == {
        "completeness": True,
        "accuracy": True,
        "freshness": True,
        "traceability": True,
    }
    assert load_context(harness)[0]["context_hash"] == current["context_hash"]

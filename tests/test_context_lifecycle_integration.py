"""Classify-to-evidence lifecycle uses fresh authoritative Context only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml

from test_context_builder import enable_plan_reconciliation, write_plan_artifacts

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


@pytest.mark.parametrize("name", ["plan.yaml", "plan-execution.yaml"])
@pytest.mark.parametrize("change", ["create", "edit", "delete"])
def test_enabled_plan_artifact_mutation_stales_saved_context(harness, name, change):
    from harness.context.integrity import validate_context
    from harness.context.model import ContextBuildError
    from harness.context.store import generate_context

    enable_plan_reconciliation(harness)
    if change != "create":
        write_plan_artifacts(harness)
    document = generate_context(harness)
    path = harness / name
    if change == "delete":
        path.unlink()
    elif change == "create":
        write_plan_artifacts(harness)
    else:
        with path.open("a") as stream:
            stream.write("\n# changed\n")

    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate_context(harness, document)


def test_fast_ad_hoc_plan_artifacts_remain_outside_saved_context_authority(harness):
    from harness.context.integrity import validate_context
    from harness.context.store import generate_context

    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))
    (harness / "plan.yaml").write_text("items: [")
    (harness / "plan-execution.yaml").write_text("items: [")

    document = generate_context(harness)
    assert document["control"]["plan_reconciliation"] == {"enabled": False}
    assert document["generated_from"]["plan_hash"] is None
    assert document["generated_from"]["plan_execution_hash"] is None
    assert "plan.yaml" not in document["generated_from"]["files"]
    assert "plan-execution.yaml" not in document["generated_from"]["files"]

    (harness / "plan.yaml").write_text("still: malformed: [")
    (harness / "plan-execution.yaml").write_text("changed: [")
    assert validate_context(harness, document)["freshness"] is True


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

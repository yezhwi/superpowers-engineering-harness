"""Classify-to-evidence lifecycle uses fresh authoritative Context only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml

from test_context_builder import (
    enable_plan_reconciliation,
    enable_required_architecture,
    write_plan_artifacts,
)

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


def test_required_architecture_current_survives_fresh_process_validate_and_explain(harness):
    enable_required_architecture(harness)

    generated = cli(harness.parent, "context", "--compact", "--json")
    assert generated.returncode == 0, generated.stderr
    document = json.loads(generated.stdout)
    assert document["control"]["architecture"]["status"] == "current"
    assert document["control"]["architecture"]["declared_modules"] == ["app"]

    validated = cli(harness.parent, "context", "validate", "--json")
    explained = cli(harness.parent, "context", "explain", "--json")
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["integrity"]["freshness"] is True
    assert explained.returncode == 0, explained.stderr
    assert load_context(harness)[0]["control"]["architecture"] == document["control"]["architecture"]


def test_required_missing_architecture_publishes_fixed_blocked_projection(harness):
    from harness.context.store import generate_context

    enable_required_architecture(harness, write_artifact=False)

    document = generate_context(harness, mode="compact")

    assert document["control"]["architecture"] == {
        "status": "missing",
        "fingerprint": None,
        "declared_modules": [],
        "relevant_modules": [],
        "blockers": ["ARCHITECTURE_REQUIRED"],
    }
    assert any(
        blocker["code"] == "ARCHITECTURE_REQUIRED"
        for blocker in document["control"]["blockers"]
    )


def test_required_malformed_architecture_never_replaces_saved_context(harness):
    enable_required_architecture(harness)
    assert cli(harness.parent, "context", "--json").returncode == 0
    before = {
        path.name: path.read_bytes()
        for path in (harness / "context").iterdir()
    }
    (harness / "architecture.yaml").write_text("modules: [")

    failed = cli(harness.parent, "context", "--json")

    assert failed.returncode == 2
    assert "CONTEXT_SCHEMA_INVALID" in failed.stderr
    assert {
        path.name: path.read_bytes()
        for path in (harness / "context").iterdir()
    } == before


def test_required_architecture_change_stales_saved_context(harness):
    enable_required_architecture(harness)
    assert cli(harness.parent, "context", "--json").returncode == 0
    with (harness / "architecture.yaml").open("a") as stream:
        stream.write("\n")

    stale = cli(harness.parent, "context", "validate")

    assert stale.returncode == 2
    assert "CONTEXT_STALE" in stale.stderr


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

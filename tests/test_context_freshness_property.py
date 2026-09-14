"""Canonical control-source mutations cannot leave Context fresh."""

import json
import random

import pytest
import test_context_builder
from test_context_integrity import add_core_records, build, validate

from harness import workspace
from harness.context.model import ContextBuildError

harness = test_context_builder.harness


def test_evidence_member_addition_stales_then_regenerates(harness):
    current = build(harness)
    snapshot = workspace.snapshot(harness.parent)
    evidence = {
        "type": "unit_test",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "command": "true",
        "exit_code": 0,
        "commit": snapshot.head,
        "workspace_fingerprint": snapshot.fingerprint,
        "workspace_fingerprint_after": snapshot.fingerprint,
    }
    path = harness / "evidence" / "extra.json"
    path.write_text(json.dumps(evidence))
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate(harness, current)
    regenerated = build(harness)
    assert validate(harness, regenerated)["freshness"] is True

    evidence["command"] = "false"
    path.write_text(json.dumps(evidence))
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate(harness, regenerated)


def test_random_canonical_control_source_mutations_stale_then_regenerate(harness):
    add_core_records(harness)
    candidates = [
        harness / "requirements.yaml",
        harness / "invariants.yaml",
        next((harness / "findings").glob("*.yaml")),
        next((harness / "decisions").glob("*.yaml")),
    ]

    for path in random.Random(28).sample(candidates, len(candidates)):
        current = build(harness)
        with path.open("a") as stream:
            stream.write(f"\n# changed {path.name}\n")
        with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
            validate(harness, current)
        regenerated = build(harness)
        assert validate(harness, regenerated)["freshness"] is True

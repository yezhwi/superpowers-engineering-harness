"""Production Context must reject unregistered Gate input, not merely lint it."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
import test_context_builder

from harness import quality_gate
from harness.context.integrity import build_context, validate_context
from harness.context.model import ContextBuildError
from harness.context.store import generate_context

harness = test_context_builder.harness
ROOT = Path(__file__).resolve().parents[1]


def test_cold_q2_off_context_import_stays_inside_source_scope(harness):
    task = test_context_builder.set_profile(harness, "Q2")
    alignment = test_context_builder._frozen_alignment(task["task"]["id"])
    test_context_builder.write_yaml(harness / "alignment.yaml", alignment)
    test_context_builder._write_matching_seal(harness, alignment)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "from harness.context.integrity import build_context; "
            "build_context(Path('.harness'))",
        ],
        cwd=harness.parent,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("swallow", [False, True])
def test_unregistered_gate_read_prevents_context_publication(
    harness, monkeypatch, swallow
):
    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")
    original = quality_gate.assess_gate

    def read_extra(*args, **kwargs):
        try:
            extra.read_text()
        except ContextBuildError:
            if not swallow:
                raise
        return original(*args, **kwargs)

    monkeypatch.setattr(quality_gate, "assess_gate", read_extra)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        generate_context(harness)
    assert not (harness / "context/current.yaml").exists()


def test_validate_also_rejects_new_undeclared_gate_read(harness, monkeypatch):
    document = build_context(harness)
    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")
    original = quality_gate.assess_gate

    def read_extra(*args, **kwargs):
        extra.read_text()
        return original(*args, **kwargs)

    monkeypatch.setattr(quality_gate, "assess_gate", read_extra)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        validate_context(harness, document)


def test_injected_selector_cannot_read_unregistered_input(harness):
    from harness.context.selector import DeterministicSelector

    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")

    class ReadingSelector:
        def select(self, source, policy, *, mode):
            extra.read_text()
            return DeterministicSelector().select(source, policy, mode=mode)

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        build_context(harness, selector=ReadingSelector())


def test_untracked_product_file_cannot_be_read_as_gate_input(harness, monkeypatch):
    extra = harness.parent / "extra-policy.yaml"
    extra.write_text("allow")
    original = quality_gate.assess_gate

    def read_extra(*args, **kwargs):
        extra.read_text()
        return original(*args, **kwargs)

    monkeypatch.setattr(quality_gate, "assess_gate", read_extra)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        generate_context(harness)
    assert not (harness / "context/current.yaml").exists()


def test_untracked_product_file_does_not_block_context_generation(harness):
    extra = harness.parent / "notes.txt"
    extra.write_text("local")
    document = generate_context(harness)
    assert document["generated_from"]["workspace_hash"]
    assert (harness / "context/current.yaml").exists()


def test_known_missing_canonical_evidence_remains_valid_blocked_projection(harness):
    document = generate_context(harness)
    assert document["control"]["gate"]["status"] == "BLOCKED"
    assert validate_context(harness, document)["freshness"]

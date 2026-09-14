"""Production Context must reject unregistered Gate input, not merely lint it."""

import pytest
import test_context_builder

from harness import quality_gate
from harness.context.integrity import build_context, validate_context
from harness.context.model import ContextBuildError
from harness.context.store import generate_context

harness = test_context_builder.harness


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


def test_known_missing_canonical_evidence_remains_valid_blocked_projection(harness):
    document = generate_context(harness)
    assert document["control"]["gate"]["status"] == "BLOCKED"
    assert validate_context(harness, document)["freshness"]

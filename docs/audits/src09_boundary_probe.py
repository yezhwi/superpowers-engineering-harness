"""Remaining SRC-09 boundaries, explicitly invoked outside normal regression.

PYTHONPATH=src:tests python -m pytest -q docs/audits/src09_boundary_probe.py
Synthetic repositories only. Raw metadata is intentionally not claimed to be
intercepted by Python open audit; trusted-source closure rejects it at release.
"""

import pytest
import test_context_builder
from source_boundary_checks import direct_io_lines

from harness import quality_gate, source_access
from harness.context import freshness
from harness.context.model import ContextBuildError
from harness.context.store import generate_context

harness = test_context_builder.harness


@pytest.mark.parametrize("query", ["exists", "stat"])
def test_raw_gate_metadata_requires_static_release_rejection(tmp_path, query):
    from harness.context.dependency_closure import assert_trusted_closure

    # Audit hooks see open, not raw metadata. Trusted Gate source must therefore
    # fail closure validation before it can be released.
    root = tmp_path / "harness"
    root.mkdir()
    (root / "quality_gate.py").write_text(
        f"from pathlib import Path\ndef assess_gate(): return Path('extra-policy.yaml').{query}()\n"
    )
    with pytest.raises(AssertionError, match="DIRECT_IO"):
        assert_trusted_closure(root, entries={"quality_gate"}, allowed={"quality_gate"})
    assert not (root / "context/current.yaml").exists()


def test_controlled_metadata_query_is_rejected(harness, monkeypatch):
    original = quality_gate.assess_gate

    def gate_with_metadata(*args, **kwargs):
        source_access.exists(harness / "extra-policy.yaml")
        return original(*args, **kwargs)

    monkeypatch.setattr(quality_gate, "assess_gate", gate_with_metadata)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        generate_context(harness)


def test_new_indirect_helper_requires_dependency_review(tmp_path):
    from harness.context.dependency_closure import assert_trusted_closure

    # No dynamic reflection: an ordinary helper import must enter the closure.
    root = tmp_path / "harness"
    root.mkdir()
    (root / "quality_gate.py").write_text(
        "from .accidental_config import is_enabled\nis_enabled()\n"
    )
    (root / "accidental_config.py").write_text(
        "from pathlib import Path\ndef is_enabled(): return Path('x').exists()\n"
    )
    with pytest.raises(AssertionError, match="DEPENDENCY_CLOSURE_UNDECLARED"):
        assert_trusted_closure(root, entries={"quality_gate"})


def test_bootstrap_new_undeclared_read_must_not_publish(harness, monkeypatch):
    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")
    original = freshness._declared_paths

    def bootstrap_with_input(*args, **kwargs):
        if extra.read_text() != "allow":
            raise ValueError("extra policy denied")
        return original(*args, **kwargs)

    monkeypatch.setattr(freshness, "_declared_paths", bootstrap_with_input)
    with pytest.raises(ContextBuildError):
        generate_context(harness)
    assert not (harness / "context/current.yaml").exists()


def test_direct_metadata_reference_is_detected_statically():
    assert direct_io_lines(
        "from pathlib import Path\nPath('extra-policy.yaml').exists()"
    )

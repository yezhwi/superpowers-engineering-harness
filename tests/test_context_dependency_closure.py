"""Trusted Context projection dependencies must be explicitly reviewed."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_current_trusted_closure_is_complete_and_direct_io_clean():
    from harness.context.dependency_closure import assert_trusted_closure

    assert_trusted_closure(ROOT / "src/harness")


def test_unknown_helper_import_is_rejected(tmp_path):
    from harness.context.dependency_closure import assert_trusted_closure

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


@pytest.mark.parametrize("query", ["exists", "stat", "is_file"])
def test_trusted_gate_direct_metadata_is_rejected(query, tmp_path):
    from harness.context.dependency_closure import assert_trusted_closure

    root = tmp_path / "harness"
    root.mkdir()
    (root / "quality_gate.py").write_text(
        f"from pathlib import Path\ndef gate(): return Path('extra-policy.yaml').{query}()\n"
    )
    with pytest.raises(AssertionError, match="DIRECT_IO"):
        assert_trusted_closure(root, entries={"quality_gate"}, allowed={"quality_gate"})


def test_declared_helper_with_direct_io_is_rejected(tmp_path):
    from harness.context.dependency_closure import assert_trusted_closure

    root = tmp_path / "harness"
    root.mkdir()
    (root / "quality_gate.py").write_text("from .adapter import read\nread()\n")
    (root / "adapter.py").write_text(
        "from pathlib import Path\ndef read(): return Path('x').read_text()\n"
    )
    with pytest.raises(AssertionError, match="DIRECT_IO"):
        assert_trusted_closure(
            root, entries={"quality_gate"}, allowed={"quality_gate", "adapter"}
        )


def test_explicit_adapter_exception_requires_reason(tmp_path):
    from harness.context.dependency_closure import assert_trusted_closure

    root = tmp_path / "harness"
    root.mkdir()
    (root / "adapter.py").write_text(
        "from pathlib import Path\ndef read(): return Path('x').read_text()\n"
    )
    with pytest.raises(AssertionError, match="ADAPTER_REASON_REQUIRED"):
        assert_trusted_closure(
            root, entries={"adapter"}, allowed={"adapter"}, adapters={"adapter": ""}
        )
    assert_trusted_closure(
        root,
        entries={"adapter"},
        allowed={"adapter"},
        adapters={"adapter": "native boundary"},
    )

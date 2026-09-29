"""Trusted Context projection dependencies must be explicitly reviewed."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_current_trusted_closure_is_complete_and_direct_io_clean():
    from harness.context.dependency_closure import assert_trusted_closure

    assert_trusted_closure(ROOT / "src/harness")


def test_plan_reconciliation_is_reviewed_code_not_adapter():
    from harness.context.dependency_closure import ADAPTERS, ALLOWED

    assert "plan_reconciliation" in ALLOWED
    assert "plan_reconciliation" not in ADAPTERS


def test_plan_automation_is_reviewed_code_not_adapter():
    from harness.context.dependency_closure import ADAPTERS, ALLOWED

    assert "plan_automation" in ALLOWED
    assert "plan_automation" not in ADAPTERS


def test_quality_gate_closure_accepts_plan_automation_source_access():
    from harness.context.dependency_closure import assert_trusted_closure

    assert_trusted_closure(ROOT / "src/harness", entries={"quality_gate"})


def test_gate_closure_does_not_import_cli_projection_modules():
    import ast

    from harness.context.dependency_closure import _imports

    root = ROOT / "src/harness"
    gate_imports = _imports(ast.parse((root / "quality_gate.py").read_text()), "quality_gate")
    reconciliation_imports = _imports(
        ast.parse((root / "plan_reconciliation.py").read_text()),
        "plan_reconciliation",
    )

    assert "plan_markdown" not in gate_imports | reconciliation_imports
    assert "plan_reporting" not in gate_imports | reconciliation_imports


def test_source_access_guarded_evidence_reads_are_accepted(tmp_path):
    from harness.context.dependency_closure import assert_trusted_closure

    root = tmp_path / "harness"
    root.mkdir()
    (root / "plan_automation.py").write_text(
        "from harness import source_access\n"
        "def read(path): return source_access.read_text(path)\n"
    )
    assert_trusted_closure(
        root,
        entries={"plan_automation"},
        allowed={"plan_automation", "source_access"},
        adapters={"source_access": "audited source access"},
    )


@pytest.mark.parametrize("operation", ["read_text", "glob"])
def test_unguarded_evidence_reads_are_rejected(tmp_path, operation):
    from harness.context.dependency_closure import assert_trusted_closure

    root = tmp_path / "harness"
    root.mkdir()
    (root / "plan_automation.py").write_text(
        f"from pathlib import Path\ndef read(): return Path('evidence').{operation}('*.json')\n"
        if operation == "glob"
        else "from pathlib import Path\ndef read(): return Path('evidence/x.json').read_text()\n"
    )
    with pytest.raises(AssertionError, match="DIRECT_IO"):
        assert_trusted_closure(
            root,
            entries={"plan_automation"},
            allowed={"plan_automation"},
            adapters={},
        )


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

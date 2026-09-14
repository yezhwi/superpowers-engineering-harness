"""Initial migrated-module boundary, not a claim about the entire Gate closure."""

import hashlib
from pathlib import Path

import pytest
import test_context_builder

from harness.context.source import FileContextSource

harness = test_context_builder.harness
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module", ["context/source.py", "context/integrity.py", "risk_boundaries.py"]
)
def test_migrated_modules_have_no_direct_filesystem_reads(module):
    from source_boundary_checks import direct_io_lines

    violations = direct_io_lines((ROOT / "src/harness" / module).read_text())
    assert violations == [], f"{module}: direct I/O at lines {violations}"


def test_document_rejects_external_reference_before_read(
    harness, monkeypatch, tmp_path_factory
):
    from harness.context.model import ContextBuildError

    external = tmp_path_factory.mktemp("external-source") / "secret.yaml"
    external.write_text("private: value\n")
    link = harness / "probe.yaml"
    link.symlink_to(external)
    actual_read = Path.read_bytes

    def forbid_external(self):
        assert self != link, "external source was read before containment check"
        return actual_read(self)

    monkeypatch.setattr(Path, "read_bytes", forbid_external)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        FileContextSource(harness)._document("probe.yaml")


def test_document_hash_and_parser_use_same_bytes(harness, monkeypatch):
    path = harness / "probe.yaml"
    original = b"value: original\n"
    path.write_bytes(original)
    actual_read = Path.read_bytes

    def mutate_after_read(self):
        content = actual_read(self)
        if self == path:
            self.write_text("value: changed\n")
        return content

    monkeypatch.setattr(Path, "read_bytes", mutate_after_read)
    loader = FileContextSource(harness)
    document = loader._document("probe.yaml")
    assert document == {"value": "original"}
    assert (
        loader.references["probe.yaml"]["sha256"]
        == "sha256:" + hashlib.sha256(original).hexdigest()
    )

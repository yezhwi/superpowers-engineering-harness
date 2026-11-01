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


def test_self_hosted_cold_batch_consumer_keeps_cache_and_data_outside_scope(tmp_path):
    import py_compile
    import shutil

    from test_finding_closure import batch_repo
    from test_finding_transition import cli

    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    package = tmp_path / "src" / "harness"
    shutil.copytree(ROOT / "src" / "harness", package,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    root, _, refs, _ = batch_repo.__wrapped__(tmp_path)
    verified = cli(tmp_path, "finding", "transition", "FND-001", "VERIFIED",
                   "--evidence", refs["a"], "--evidence", refs["b"])
    assert verified.returncode == 0, verified.stdout + verified.stderr
    closed = cli(tmp_path, "finding", "transition", "FND-001", "CLOSED")
    assert closed.returncode == 0, closed.stdout + closed.stderr
    cache = py_compile.compile(str(package / "finding_closure.py"), doraise=True)
    assert Path(cache).is_file()
    (root / "private-input.txt").write_text("undeclared fixture data")
    program = """
import sys
from pathlib import Path
import yaml
from harness.context.read_scope import context_read_scope
from harness.context.model import ContextBuildError
from harness.quality_gate import _validate_finding_proofs
from harness.workspace import snapshot
from harness.schema_resources import schema_versions

root = Path('.harness').absolute()
finding = yaml.safe_load((root / 'findings/FND-001.yaml').read_bytes())
impact = yaml.safe_load((root / 'impact.yaml').read_bytes())
current = snapshot(root.parent)
versions = {'files': {}, 'declared_files': {},
            'schema_resources': {'evidence.schema.json': schema_versions()['evidence.schema.json']}}
assert 'harness.finding_closure' not in sys.modules, 'consumer must start cold'
with context_read_scope(root, versions):
    _validate_finding_proofs(root, [finding], impact, current.head, current.fingerprint)
for forbidden in (root / 'private-input.txt', Path(sys.argv[1])):
    try:
        with context_read_scope(root, versions):
            forbidden.read_bytes()
    except ContextBuildError as error:
        assert 'CONTEXT_REFERENCE_BROKEN' in str(error)
    else:
        raise AssertionError('scope widened to unregistered data/cache')
print('COLD_BATCH_CONSUMER_AND_NEGATIVE_SCOPE_OK')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, cache], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path / "src")},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COLD_BATCH_CONSUMER_AND_NEGATIVE_SCOPE_OK" in result.stdout


def test_context_scope_rejects_same_name_dir_fd_read_from_harness(harness):
    from harness.context.read_scope import context_read_scope

    product = harness.parent / "collision.txt"
    hidden = harness / "collision.txt"
    product.write_text("allowed product")
    hidden.write_text("undeclared control")
    versions = {
        "files": {"current-task.yaml": "sha256:" + "0" * 64},
        "declared_files": {"collision.txt": "sha256:" + "0" * 64},
        "schema_resources": {},
    }

    directory = os.open(harness, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
            with context_read_scope(harness, versions):
                descriptor = os.open("collision.txt", os.O_RDONLY, dir_fd=directory)
                os.close(descriptor)
    finally:
        os.close(directory)


def test_off_context_scope_rejects_unversioned_architecture_schema(
    harness, monkeypatch
):
    from harness import schema_resources
    from harness.context.freshness import capture
    from harness.context.read_scope import context_read_scope

    versions = capture(harness)
    assert "architecture.schema.json" not in versions["schema_resources"]
    reads = []
    original = schema_resources._resource_bytes

    def recording_resource(name):
        reads.append(name)
        return original(name)

    monkeypatch.setattr(schema_resources, "_resource_bytes", recording_resource)

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with context_read_scope(harness, versions):
            schema_resources.read_schema("architecture.schema.json")
    assert "architecture.schema.json" not in reads


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

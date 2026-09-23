"""CLI publishes one validated Context bundle, never partial stdout or task edits."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml
from test_context_builder import write_yaml
from test_context_integrity import add_core_records as add_records

from harness import decision
from harness.context.model import ContextBuildError

harness = test_context_builder.harness
REPO = Path(__file__).resolve().parents[1]


def add_core_records(root):
    """Keep CLI projection fixtures local; automatic triggers have separate tests."""
    add_records(root)
    path = next((root / "decisions").glob("*.yaml"))
    record = yaml.safe_load(path.read_text())
    record["scope"] = ["src/local.py"]
    write_yaml(path, record)
    decision.reindex(root)


def run_cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", "context", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )


def bundle_bytes(root):
    directory = root / "context"
    return {
        name: (directory / name).read_bytes()
        for name in ("current.yaml", "manifest.yaml", "evidence.yaml")
        if (directory / name).exists()
    }


@pytest.mark.parametrize(
    "flags,mode",
    [
        ((), "compact"),
        (("--compact",), "compact"),
        (("--full",), "full"),
        (("--json",), "compact"),
        (("--full", "--json"), "full"),
    ],
)
def test_cli_generation_saves_matching_bundle_and_prints_only_document(
    harness, flags, mode
):
    add_core_records(harness)
    task_before = (harness / "current-task.yaml").read_bytes()
    products_before = {p.name: p.read_bytes() for p in (harness / "evidence").iterdir()}
    result = run_cli(harness.parent, *flags)
    assert result.returncode == 0, result.stderr
    document = (
        json.loads(result.stdout)
        if "--json" in flags
        else yaml.safe_load(result.stdout)
    )
    assert document["mode"] == mode
    current = yaml.safe_load((harness / "context/current.yaml").read_text())
    manifest = yaml.safe_load((harness / "context/manifest.yaml").read_text())
    evidence = yaml.safe_load((harness / "context/evidence.yaml").read_text())
    assert current == document
    assert manifest == {
        "context_hash": document["context_hash"],
        **document["manifest"],
    }
    assert evidence["context_hash"] == current["context_hash"]
    assert evidence["task_id"] == "TASK-028"
    assert evidence["policy"] == evidence["base_policy"] == "LOCAL"
    assert evidence["integrity"] == {
        "completeness": True,
        "accuracy": True,
        "freshness": True,
        "traceability": True,
    }
    assert evidence["included"]["requirements"] == (
        ["REQ-001", "REQ-002"] if mode == "full" else ["REQ-001"]
    )
    assert evidence["generated_from"] == document["generated_from"]
    assert evidence["omitted"] == document["omitted"]
    assert evidence["expansions"] == []
    assert evidence["generated_at"]
    assert (harness / "current-task.yaml").read_bytes() == task_before
    assert {
        p.name: p.read_bytes() for p in (harness / "evidence").iterdir()
    } == products_before
    assert not (harness / "telemetry.json").exists()


def test_cli_validate_is_read_only_and_detects_stale_without_regenerating(harness):
    assert run_cli(harness.parent).returncode == 0
    before = bundle_bytes(harness)
    result = run_cli(harness.parent, "validate", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["integrity"]["freshness"] is True
    assert bundle_bytes(harness) == before
    with (harness / "requirements.yaml").open("a") as stream:
        stream.write("\n# changed\n")
    stale = run_cli(harness.parent, "validate")
    assert stale.returncode == 2
    assert "CONTEXT_STALE" in stale.stderr
    assert stale.stdout == ""
    assert bundle_bytes(harness) == before
    assert run_cli(harness.parent).returncode == 0
    assert run_cli(harness.parent, "validate").returncode == 0


def test_cli_explain_reports_saved_selection_and_global_reasons(harness):
    add_core_records(harness)
    assert run_cli(harness.parent).returncode == 0
    before = bundle_bytes(harness)
    result = run_cli(harness.parent, "explain", "--json")
    assert result.returncode == 0, result.stderr
    explanation = json.loads(result.stdout)
    assert explanation["policy"] == "LOCAL"
    assert any(
        r["id"] == "REQ-001" and r["reason"] == "mandatory_global_core"
        for r in explanation["global"]
    )
    assert any(
        r["id"] == "REQ-002" and r["reason"] == "unrelated_to_scope"
        for r in explanation["omitted"]
    )
    assert any(
        r["id"] == "src/local.py" and r["reason"] for r in explanation["included"]
    )
    assert explanation["expansions"] == []
    assert bundle_bytes(harness) == before


@pytest.mark.parametrize("action", [(), ("validate",), ("explain",)])
def test_context_requires_task_and_never_initializes_one(harness, action):
    (harness / "current-task.yaml").unlink()
    result = run_cli(harness.parent, *action)
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr
    assert result.stdout == ""
    assert not (harness / "context").exists()


@pytest.mark.parametrize("action", ["validate", "explain"])
def test_read_commands_require_existing_snapshot(harness, action):
    result = run_cli(harness.parent, action)
    assert result.returncode == 2
    assert result.stdout == ""
    assert not (harness / "context").exists()


def test_failed_integrity_does_not_publish_or_print_partial_context(harness):
    assert run_cli(harness.parent).returncode == 0
    before = bundle_bytes(harness)
    write_yaml(harness / "requirements.yaml", {"requirements": "invalid"})
    result = run_cli(harness.parent, "--full")
    assert result.returncode == 2
    assert "CONTEXT_SCHEMA_INVALID" in result.stderr
    assert result.stdout == ""
    assert bundle_bytes(harness) == before


def test_cli_works_from_repository_subdirectory(harness):
    sub = harness.parent / "nested"
    sub.mkdir()
    result = run_cli(sub, "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["control"]["task"]["id"] == "TASK-028"
    assert not (sub / ".harness").exists()


@pytest.mark.parametrize("member", ["manifest.yaml", "evidence.yaml"])
def test_mixed_or_tampered_companion_is_rejected(harness, member):
    assert run_cli(harness.parent).returncode == 0
    path = harness / "context" / member
    document = yaml.safe_load(path.read_text())
    document["context_hash"] = "sha256:" + "0" * 64
    write_yaml(path, document)
    result = run_cli(harness.parent, "validate")
    assert result.returncode == 2
    assert "CONTEXT_INACCURATE" in result.stderr
    assert result.stdout == ""


def test_context_evidence_cannot_forge_included_facts(harness):
    assert run_cli(harness.parent).returncode == 0
    path = harness / "context/evidence.yaml"
    evidence = yaml.safe_load(path.read_text())
    evidence["included"]["requirements"] = ["REQ-999"]
    write_yaml(path, evidence)
    result = run_cli(harness.parent, "validate")
    assert result.returncode == 2
    assert "CONTEXT_INACCURATE" in result.stderr


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_publication_failure_restores_last_complete_bundle(
    harness, monkeypatch, failure
):
    from harness.context.store import generate_context

    generate_context(harness)
    before = bundle_bytes(harness)
    original = Path.replace

    def fail_manifest(self, target):
        if Path(target) == harness / "context/manifest.yaml":
            raise failure("injected manifest publication failure")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", fail_manifest)
    with pytest.raises((ContextBuildError, failure)):
        generate_context(harness, mode="full")
    assert bundle_bytes(harness) == before
    assert not list((harness / "context").glob("*.tmp"))
    assert not list((harness / ".staging").glob("context-*"))


def test_source_change_during_publication_rolls_back_new_bundle(harness, monkeypatch):
    from harness import transaction
    from harness.context.store import generate_context

    generate_context(harness)
    before = bundle_bytes(harness)
    original = transaction.publish

    def mutate_source(*args, **kwargs):
        original(*args, **kwargs)
        with (harness / "requirements.yaml").open("a") as stream:
            stream.write("\n# concurrent change\n")

    monkeypatch.setattr(transaction, "publish", mutate_source)
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        generate_context(harness, mode="full")
    assert bundle_bytes(harness) == before


def test_context_destination_cannot_be_an_external_symlink(harness, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside-context-output")
    (harness / "context").symlink_to(outside, target_is_directory=True)
    result = run_cli(harness.parent)
    assert result.returncode == 2
    assert "CONTEXT_REFERENCE_BROKEN" in result.stderr
    assert result.stdout == ""
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("flags", [("--json", "validate"), ("validate", "--json")])
def test_json_flag_works_before_or_after_read_subcommand(harness, flags):
    assert run_cli(harness.parent).returncode == 0
    result = run_cli(harness.parent, *flags)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["integrity"]["freshness"]


@pytest.mark.parametrize("member", ["current.yaml", "manifest.yaml", "evidence.yaml"])
def test_unreadable_or_missing_bundle_member_has_no_stdout(harness, member):
    assert run_cli(harness.parent).returncode == 0
    (harness / "context" / member).unlink()
    result = run_cli(harness.parent, "validate")
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("member", ["context/current.yaml", ".staging"])
def test_output_member_and_staging_symlinks_cannot_escape(
    harness, tmp_path_factory, member
):
    outside = tmp_path_factory.mktemp("outside-context-member")
    path = harness / member
    path.parent.mkdir(exist_ok=True)
    target = outside if member == ".staging" else outside / "output.yaml"
    path.symlink_to(target, target_is_directory=member == ".staging")
    result = run_cli(harness.parent)
    assert result.returncode == 2
    assert "CONTEXT_REFERENCE_BROKEN" in result.stderr
    assert result.stdout == ""
    assert list(outside.iterdir()) == []


def test_context_reads_wait_for_complete_bundle_publication(harness, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    from harness.context.store import generate_context, load_context

    generate_context(harness)
    entered, release, reader_started = Event(), Event(), Event()
    original = Path.replace

    def pause_after_current(self, target):
        result = original(self, target)
        if Path(target) == harness / "context/current.yaml":
            entered.set()
            assert release.wait(10)
        return result

    def read():
        reader_started.set()
        return load_context(harness)

    monkeypatch.setattr(Path, "replace", pause_after_current)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(generate_context, harness, mode="full")
        try:
            assert entered.wait(10)
            reader = pool.submit(read)
            assert reader_started.wait(10)
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.2)
        finally:
            release.set()
        document = writer.result(timeout=15)
        saved, integrity = reader.result(timeout=15)
    assert saved == document
    assert saved["mode"] == "full"
    assert integrity["freshness"]


@pytest.mark.parametrize("flags", [("--full", "--compact"), ("--full", "validate")])
def test_cli_rejects_conflicting_or_ignored_mode_flags(harness, flags):
    result = run_cli(harness.parent, *flags)
    assert result.returncode == 2
    assert not (harness / "context").exists()

"""Architecture artifact store and CLI contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from harness import architecture_store
from harness.architecture import ArchitectureError

REPO = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )


def repository(tmp_path: Path, *, state: str = "SPECIFYING") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    assert cli(repo, "init").returncode == 0
    source = repo / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("SECRET_BODY = True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    task_path = repo / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = state
    task["task"]["id"] = "TASK-001"
    task["git"]["base_commit"] = git(repo, "rev-parse", "HEAD")
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    return repo


def architecture_document() -> dict:
    return {
        "version": 1,
        "modules": [
            {
                "id": "app",
                "name": "Application",
                "responsibility": "Run application logic.",
                "depends_on": [],
                "evidence": [{"type": "source", "path": "src/app.py"}],
            }
        ],
        "ownership": [
            {
                "id": "OWN-001",
                "pattern": "src/**",
                "kind": "production",
                "modules": ["app"],
            }
        ],
    }


def candidate(tmp_path: Path, document: dict | None = None) -> Path:
    path = tmp_path / "candidate.yaml"
    path.write_text(
        yaml.safe_dump(document or architecture_document(), sort_keys=False),
        encoding="utf-8",
    )
    return path


def harness_bytes(repo: Path) -> dict[str, bytes]:
    root = repo / ".harness"
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_load_optional_missing_and_required_missing(tmp_path):
    repo = repository(tmp_path)
    harness = repo / ".harness"

    assert architecture_store.load_architecture(harness, required=False) is None
    with pytest.raises(ArchitectureError) as exc:
        architecture_store.load_architecture(harness, required=True)
    assert exc.value.code == "ARCHITECTURE_REQUIRED"


def test_publish_validates_candidate_before_any_write(tmp_path):
    repo = repository(tmp_path)
    bad = candidate(tmp_path, {"version": 1})
    before = harness_bytes(repo)

    with pytest.raises(ArchitectureError):
        architecture_store.publish_architecture(repo / ".harness", bad)

    assert harness_bytes(repo) == before


@pytest.mark.parametrize(
    "state",
    [
        "CREATED",
        "CLASSIFIED",
        "PLANNED",
        "VERIFYING",
        "REVIEWING",
        "GATING",
        "BLOCKED",
        "REPRODUCING",
        "FIXING",
        "CONVERGED",
        "DONE",
        "ESCALATED",
    ],
)
def test_publish_outside_specifying_has_zero_writes(tmp_path, state):
    repo = repository(tmp_path, state=state)
    before = harness_bytes(repo)

    with pytest.raises(ArchitectureError) as exc:
        architecture_store.publish_architecture(
            repo / ".harness", candidate(tmp_path)
        )

    assert exc.value.code == "ARCHITECTURE_MUTATION_STATE_INVALID"
    assert harness_bytes(repo) == before


def test_implementing_publish_requires_realign_and_has_zero_writes(tmp_path):
    repo = repository(tmp_path, state="IMPLEMENTING")
    before = harness_bytes(repo)

    with pytest.raises(ArchitectureError) as exc:
        architecture_store.publish_architecture(
            repo / ".harness", candidate(tmp_path)
        )

    assert exc.value.code == "ARCHITECTURE_REALIGNMENT_REQUIRED"
    assert harness_bytes(repo) == before


def test_publish_rejects_missing_evidence_empty_rule_duplicate_and_conflict(tmp_path):
    repo = repository(tmp_path)
    harness = repo / ".harness"

    missing_evidence = architecture_document()
    missing_evidence["modules"][0]["evidence"][0]["path"] = "src/missing.py"
    with pytest.raises(ArchitectureError) as exc:
        architecture_store.publish_architecture(
            harness, candidate(tmp_path, missing_evidence)
        )
    assert exc.value.code == "ARCHITECTURE_EVIDENCE_INVALID"

    empty_rule = architecture_document()
    empty_rule["ownership"][0]["pattern"] = "missing/**"
    with pytest.raises(ArchitectureError) as exc:
        architecture_store.publish_architecture(harness, candidate(tmp_path, empty_rule))
    assert exc.value.code == "ARCHITECTURE_OWNERSHIP_EMPTY"

    duplicate = architecture_document()
    extra = deepcopy(duplicate["ownership"][0])
    extra["id"] = "OWN-002"
    duplicate["ownership"].append(extra)
    with pytest.raises(ArchitectureError) as exc:
        architecture_store.publish_architecture(harness, candidate(tmp_path, duplicate))
    assert exc.value.code == "ARCHITECTURE_MODEL_INVALID"

    conflict = architecture_document()
    conflict["modules"].append(
        {
            "id": "other",
            "name": "Other",
            "responsibility": "Own conflicting paths.",
            "depends_on": [],
            "evidence": [{"type": "source", "path": "src/app.py"}],
        }
    )
    conflict["ownership"].append(
        {
            "id": "OWN-002",
            "pattern": "src/**",
            "kind": "production",
            "modules": ["other"],
        }
    )
    with pytest.raises(ArchitectureError) as exc:
        architecture_store.publish_architecture(harness, candidate(tmp_path, conflict))
    assert exc.value.code == "ARCHITECTURE_OWNERSHIP_AMBIGUOUS"


def test_allow_empty_rule_can_publish_without_matching_current_path(tmp_path):
    repo = repository(tmp_path)
    document = architecture_document()
    document["ownership"][0].update(
        pattern="future/**", allow_empty=True, empty_reason="Planned path."
    )

    assert architecture_store.publish_architecture(
        repo / ".harness", candidate(tmp_path, document)
    )


def test_semantic_retry_is_noop_and_preserves_canonical_bytes(tmp_path):
    repo = repository(tmp_path)
    harness = repo / ".harness"
    first = candidate(tmp_path)
    assert architecture_store.publish_architecture(harness, first)
    canonical = harness / "architecture.yaml"
    before = canonical.read_bytes()
    document = architecture_document()
    document["modules"] = list(reversed(document["modules"]))
    retry = tmp_path / "retry.yaml"
    retry.write_text(yaml.safe_dump(document, sort_keys=True))

    assert architecture_store.publish_architecture(harness, retry) is False
    assert canonical.read_bytes() == before


def test_valid_candidate_repairs_malformed_canonical_artifact(tmp_path):
    repo = repository(tmp_path)
    harness = repo / ".harness"
    canonical = harness / "architecture.yaml"
    canonical.write_text("modules: [")

    assert architecture_store.publish_architecture(harness, candidate(tmp_path))
    assert architecture_store.load_architecture(harness, required=True) is not None


def test_publish_uses_lock_and_transaction_rollback(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    harness = repo / ".harness"
    assert architecture_store.publish_architecture(harness, candidate(tmp_path))
    canonical = harness / "architecture.yaml"
    before = canonical.read_bytes()
    entered = []

    @contextmanager
    def lock(_harness):
        entered.append(True)
        yield

    changed = architecture_document()
    changed["modules"][0]["responsibility"] = "Changed responsibility."
    replacement = candidate(tmp_path, changed)
    original_replace = Path.replace

    def fail_canonical(source, target):
        if target == canonical:
            raise OSError("injected publish failure")
        return original_replace(source, target)

    monkeypatch.setattr(architecture_store, "telemetry_lock", lock)
    monkeypatch.setattr(Path, "replace", fail_canonical)
    with pytest.raises(OSError, match="injected publish failure"):
        architecture_store.publish_architecture(harness, replacement)

    assert entered == [True]
    assert canonical.read_bytes() == before


def test_scope_add_remove_is_specifying_only_and_creates_no_authority_artifacts(tmp_path):
    repo = repository(tmp_path)
    harness = repo / ".harness"
    architecture_store.publish_architecture(harness, candidate(tmp_path))
    before_names = set(harness_bytes(repo))

    assert architecture_store.mutate_architecture_scope(harness, "add", "app")
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    assert task["scope"]["modules"] == ["app"]
    assert architecture_store.mutate_architecture_scope(harness, "add", "app") is False
    assert architecture_store.mutate_architecture_scope(harness, "remove", "app")
    task = yaml.safe_load(task_path.read_text())
    assert task["scope"]["modules"] == []
    assert set(harness_bytes(repo)) == before_names
    assert not (harness / "alignment-freeze.yaml").exists()


def test_scope_mutation_in_implementing_has_zero_writes(tmp_path):
    repo = repository(tmp_path)
    harness = repo / ".harness"
    architecture_store.publish_architecture(harness, candidate(tmp_path))
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = "IMPLEMENTING"
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    before = harness_bytes(repo)

    with pytest.raises(ArchitectureError) as exc:
        architecture_store.mutate_architecture_scope(harness, "add", "app")

    assert exc.value.code == "ARCHITECTURE_REALIGNMENT_REQUIRED"
    assert harness_bytes(repo) == before


def test_cli_publish_and_scope_commands_report_mutation_results(tmp_path):
    repo = repository(tmp_path)
    source = candidate(tmp_path)

    published = cli(repo, "architecture", "publish", "--file", str(source))
    added = cli(repo, "architecture", "scope", "add", "app")
    unchanged = cli(repo, "architecture", "scope", "add", "app")

    assert (published.returncode, published.stdout) == (0, "ARCHITECTURE_PUBLISHED\n")
    assert (added.returncode, added.stdout) == (0, "ARCHITECTURE_SCOPE_UPDATED\n")
    assert (unchanged.returncode, unchanged.stdout) == (
        0,
        "ARCHITECTURE_SCOPE_UNCHANGED\n",
    )


def test_read_commands_are_deterministic_read_only_json_and_body_free(tmp_path):
    repo = repository(tmp_path)
    source = candidate(tmp_path)
    assert cli(repo, "architecture", "publish", "--file", str(source)).returncode == 0
    assert cli(repo, "architecture", "scope", "add", "app").returncode == 0
    before = harness_bytes(repo)

    commands = (
        ("validate",),
        ("resolve", "src/app.py"),
        ("check",),
    )
    for command in commands:
        first = cli(repo, "architecture", *command, "--json")
        second = cli(repo, "architecture", *command, "--json")
        assert first.returncode == 0, first.stderr
        assert first.stdout == second.stdout
        assert isinstance(json.loads(first.stdout), dict)
        assert "SECRET_BODY" not in first.stdout
    assert harness_bytes(repo) == before


def test_read_commands_offer_stable_text_output(tmp_path):
    repo = repository(tmp_path)
    assert cli(
        repo, "architecture", "publish", "--file", str(candidate(tmp_path))
    ).returncode == 0

    assert cli(repo, "architecture", "validate").stdout.startswith("Architecture: VALID")
    assert "resolved" in cli(
        repo, "architecture", "resolve", "src/app.py"
    ).stdout
    assert cli(repo, "architecture", "check").stdout.startswith("Architecture check:")


def test_read_command_rejects_malformed_present_artifact_without_writes(tmp_path):
    repo = repository(tmp_path)
    artifact = repo / ".harness" / "architecture.yaml"
    artifact.write_text("modules: [")
    before = harness_bytes(repo)

    result = cli(repo, "architecture", "validate", "--json")

    assert result.returncode == 1
    assert "ARCHITECTURE_SCHEMA_INVALID" in result.stderr
    assert harness_bytes(repo) == before

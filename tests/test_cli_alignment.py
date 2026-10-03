import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from harness.alignment import ArchitectureFreezeFacts

REPO = Path(__file__).resolve().parent.parent


def cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    task = yaml.safe_load((tmp_path / ".harness/current-task.yaml").read_text())
    task["task"]["id"] = "TASK-001"
    task["task"]["description"] = "alignment CLI task"
    (tmp_path / ".harness/current-task.yaml").write_text(yaml.safe_dump(task))
    return tmp_path


def test_align_init_creates_draft_once_and_refuses_overwrite(tmp_path):
    path = repo(tmp_path)

    created = cli(path, "align", "init")
    artifact = path / ".harness/alignment.yaml"
    before = artifact.read_bytes()
    refused = cli(path, "align", "init")

    assert created.returncode == 0, created.stderr
    assert yaml.safe_load(before)["freeze"]["frozen"] is False
    assert refused.returncode == 1
    assert artifact.read_bytes() == before


def test_align_freeze_seals_complete_draft_without_task_transition(tmp_path):
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    harness = path / ".harness"
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    before_task = (harness / "current-task.yaml").read_bytes()

    result = cli(path, "align", "freeze")

    assert result.returncode == 0, result.stderr
    sealed = yaml.safe_load((harness / "alignment.yaml").read_text())
    assert sealed["freeze"]["frozen"] is True
    freeze = yaml.safe_load((harness / "alignment-freeze.yaml").read_text())
    assert freeze["version"] == 2
    assert freeze["architecture_mode"] == "off"
    assert freeze["architecture_fingerprint"] is None
    assert freeze["declared_modules"] == []
    assert (harness / "current-task.yaml").read_bytes() == before_task


def test_required_align_freeze_rejects_missing_scope_before_architecture_read(tmp_path):
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    harness = path / ".harness"
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    gate_path = harness / "gate.yaml"
    gate = yaml.safe_load(gate_path.read_text())
    gate["gate"]["architecture"]["mode"] = "required"
    gate_path.write_text(yaml.safe_dump(gate, sort_keys=False))
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["scope"].pop("modules")
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    (harness / "architecture.yaml").write_text("malformed: [")
    before = {name: (harness / name).read_bytes() for name in ("alignment.yaml", "current-task.yaml", "architecture.yaml")}

    result = cli(path, "align", "freeze")

    assert result.returncode == 2
    assert "ARCHITECTURE_SCOPE_DECLARATION_REQUIRED" in result.stderr
    assert not (harness / "alignment-freeze.yaml").exists()
    assert {name: (harness / name).read_bytes() for name in before} == before


def test_required_align_freeze_accepts_explicit_empty_support_scope(tmp_path):
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    harness = path / ".harness"
    source = path / "support.txt"
    source.write_text("support")
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    gate = yaml.safe_load((harness / "gate.yaml").read_text())
    gate["gate"]["architecture"]["mode"] = "required"
    (harness / "gate.yaml").write_text(yaml.safe_dump(gate, sort_keys=False))
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["scope"]["modules"] = []
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task, sort_keys=False))
    architecture = {
        "version": 1,
        "modules": [{"id": "app", "name": "App", "responsibility": "Run app.", "depends_on": [], "evidence": [{"type": "source", "path": "support.txt"}]}],
        "ownership": [{"id": "OWN-001", "pattern": "support.txt", "kind": "support", "modules": []}],
    }
    (harness / "architecture.yaml").write_text(yaml.safe_dump(architecture, sort_keys=False))

    result = cli(path, "align", "freeze")

    assert result.returncode == 0, result.stderr
    freeze = yaml.safe_load((harness / "alignment-freeze.yaml").read_text())
    assert freeze["version"] == 2
    assert freeze["architecture_mode"] == "required"
    assert freeze["architecture_fingerprint"].startswith("sha256:")
    assert freeze["declared_modules"] == []


def test_align_freeze_rejects_proposed_decision_without_directive(tmp_path):
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    harness = path / ".harness"
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    assert cli(
        path,
        "decision",
        "propose",
        "--topic",
        "scope",
        "--question",
        "choose",
        "--context",
        "x",
        "--option",
        "a=A",
        "--recommend",
        "a",
        "--reason",
        "x",
    ).returncode == 0

    result = cli(path, "align", "freeze")

    assert result.returncode == 1
    assert "OPEN_DECISION" in result.stderr
    assert "DIRECTIVE:" not in result.stderr


def test_align_freeze_rejects_incomplete_draft_without_changing_artifacts(tmp_path):
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    harness = path / ".harness"
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["open_loops"] = ["LOOP-001"]
    alignment_path = harness / "alignment.yaml"
    alignment_path.write_text(yaml.safe_dump(document))
    before_alignment = alignment_path.read_bytes()
    before_task = (harness / "current-task.yaml").read_bytes()

    result = cli(path, "align", "freeze")

    assert result.returncode == 1
    assert "OPEN_LOOP" in result.stderr
    assert alignment_path.read_bytes() == before_alignment
    assert not (harness / "alignment-freeze.yaml").exists()
    assert (harness / "current-task.yaml").read_bytes() == before_task


def test_align_freeze_rolls_back_first_artifact_when_second_publish_fails(tmp_path, monkeypatch, capsys):
    from test_alignment import complete_alignment

    from harness import controlplane

    path = repo(tmp_path)
    harness = path / ".harness"
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    alignment_path = harness / "alignment.yaml"
    alignment_path.write_text(yaml.safe_dump(document))
    before_alignment = alignment_path.read_bytes()
    before_task = (harness / "current-task.yaml").read_bytes()
    original_replace = Path.replace

    def fail_second_publish(source, target):
        if target.name == "alignment-freeze.yaml":
            raise OSError("injected second publish failure")
        return original_replace(source, target)

    monkeypatch.chdir(path)
    monkeypatch.setattr(Path, "replace", fail_second_publish)

    assert controlplane.cmd_align("freeze") == 2

    assert "ALIGNMENT_FREEZE_FAILED" in capsys.readouterr().err
    assert alignment_path.read_bytes() == before_alignment
    assert not (harness / "alignment-freeze.yaml").exists()
    assert (harness / "current-task.yaml").read_bytes() == before_task


def test_align_check_rejects_unfrozen_draft(tmp_path):
    path = repo(tmp_path)
    assert cli(path, "align", "init").returncode == 0

    result = cli(path, "align", "check")

    assert result.returncode == 1
    assert "ALIGNMENT_FREEZE_INVALID" in result.stderr


def test_align_status_reports_unfrozen_state(tmp_path):
    path = repo(tmp_path)
    assert cli(path, "align", "init").returncode == 0

    result = cli(path, "align", "status")

    assert result.returncode == 0
    assert "Alignment: BLOCKED" in result.stdout
    assert "Freeze: UNFROZEN" in result.stdout


def test_align_status_rejects_frozen_open_loop(tmp_path):
    from harness.alignment import contract_hash
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["open_loops"] = ["LOOP-001"]
    document["freeze"] = {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": contract_hash(document)}
    (path / ".harness/alignment.yaml").write_text(yaml.safe_dump(document))

    result = cli(path, "align", "status")

    assert result.returncode == 1
    assert "Alignment: BLOCKED" in result.stdout
    assert "OPEN_LOOP" in result.stderr


def test_align_status_rejects_persisted_proposed_decision(tmp_path):
    from harness import decision
    from harness.alignment import contract_hash, validate_sealed_freeze
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    assert cli(path, "decision", "propose", "--topic", "scope", "--question", "choose", "--context", "x", "--option", "a=A", "--recommend", "a", "--reason", "x").returncode == 0
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["freeze"] = {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": contract_hash(document)}
    harness = path / ".harness"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    validate_sealed_freeze(
        harness, document,
        decisions=decision.load_decisions(harness),
        boundary_refs={"interface": [], "permission": [], "persistence": []},
        bootstrap_legacy_off=True,
        architecture_facts=ArchitectureFreezeFacts("off", None, ()),
    )

    result = cli(path, "align", "status")

    assert result.returncode == 1
    assert "Alignment: BLOCKED" in result.stdout
    assert "OPEN_DECISION" in result.stderr


def _required_frozen_repo(tmp_path: Path) -> Path:
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    harness = path / ".harness"
    source = path / "support.txt"
    source.write_text("support")
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    gate = yaml.safe_load((harness / "gate.yaml").read_text())
    gate["gate"]["architecture"]["mode"] = "required"
    (harness / "gate.yaml").write_text(yaml.safe_dump(gate, sort_keys=False))
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["scope"]["modules"] = ["app"]
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task, sort_keys=False))
    architecture = {
        "version": 1,
        "modules": [{"id": "app", "name": "App", "responsibility": "Run app.", "depends_on": [], "evidence": [{"type": "source", "path": "support.txt"}]}],
        "ownership": [{"id": "OWN-001", "pattern": "support.txt", "kind": "support", "modules": []}],
    }
    (harness / "architecture.yaml").write_text(yaml.safe_dump(architecture, sort_keys=False))
    frozen = cli(path, "align", "freeze")
    assert frozen.returncode == 0, frozen.stderr
    task["scope"].pop("modules")
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task, sort_keys=False))
    return path


@pytest.mark.parametrize("command", ["status", "diff"])
def test_align_read_paths_halt_when_frozen_modules_are_removed(tmp_path, command):
    path = _required_frozen_repo(tmp_path)

    result = cli(path, "align", command)

    assert result.returncode == 1
    assert "POLICY: USER_AUTHORITY_REQUIRED" in result.stderr
    assert "DIRECTIVE: HALT_AND_WAIT" in result.stderr
    assert "CONTRACT_CHANGED" in result.stderr


def test_align_diff_reports_unfrozen_contract(tmp_path):
    path = repo(tmp_path)
    assert cli(path, "align", "init").returncode == 0

    result = cli(path, "align", "diff")

    assert result.returncode == 1
    assert "ALIGNMENT_UNFROZEN" in result.stderr


def _freeze(path: Path, document: dict) -> None:
    from harness.alignment import contract_hash, validate_sealed_freeze
    from harness.decision import load_decisions

    document["task_id"] = "TASK-001"
    document["decision_ids"] = []
    document["freeze"] = {
        "frozen": True,
        "frozen_at": "2026-09-18T00:00:00+00:00",
        "contract_hash": None,
    }
    document["freeze"]["contract_hash"] = contract_hash(document)
    harness = path / ".harness"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    validate_sealed_freeze(
        harness,
        document,
        decisions=load_decisions(harness),
        boundary_refs={"interface": [], "permission": [], "persistence": []},
        bootstrap_legacy_off=True,
        architecture_facts=ArchitectureFreezeFacts("off", None, ()),
    )


def test_align_diff_detects_rewritten_in_document_hash(tmp_path):
    from harness.alignment import contract_hash
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    document = complete_alignment()
    _freeze(path, document)
    document["goal"]["summary"] = "changed after seal"
    document["freeze"]["contract_hash"] = contract_hash(document)
    (path / ".harness/alignment.yaml").write_text(yaml.safe_dump(document))

    result = cli(path, "align", "diff")

    assert result.returncode == 1
    assert "CONTRACT_CHANGED" in result.stderr


def test_align_diff_detects_accepted_option_change(tmp_path):
    from harness.alignment import contract_hash, validate_sealed_freeze
    from harness.decision import accept, load_decisions, propose
    from test_alignment import complete_alignment
    from test_decision import proposal

    path = repo(tmp_path)
    harness = path / ".harness"
    record = propose(harness, proposal())
    accept(harness, record["id"], "redis", "accepted_recommendation")
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["decision_ids"] = [record["id"]]
    document["freeze"] = {
        "frozen": True,
        "frozen_at": "2026-09-18T00:00:00+00:00",
        "contract_hash": None,
    }
    document["freeze"]["contract_hash"] = contract_hash(document)
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    validate_sealed_freeze(
        harness,
        document,
        decisions=load_decisions(harness),
        boundary_refs={"interface": [], "permission": [], "persistence": []},
        bootstrap_legacy_off=True,
        architecture_facts=ArchitectureFreezeFacts("off", None, ()),
    )
    body = yaml.safe_load((harness / "decisions" / f"{record['id']}.yaml").read_text())
    body["selected"]["option"] = "local"
    (harness / "decisions" / f"{record['id']}.yaml").write_text(yaml.safe_dump(body))

    result = cli(path, "align", "diff")

    assert result.returncode == 1
    assert "CONTRACT_CHANGED" in result.stderr


def test_align_check_prints_blocked_open_loop_and_next_action(tmp_path):
    from harness.alignment import contract_hash, validate_sealed_freeze
    from test_alignment import complete_alignment

    path = repo(tmp_path)
    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["decision_ids"] = []
    document["open_loops"] = ["LOOP-001"]
    document["freeze"] = {
        "frozen": True,
        "frozen_at": "2026-09-18T00:00:00+00:00",
        "contract_hash": None,
    }
    document["freeze"]["contract_hash"] = contract_hash(document)
    harness = path / ".harness"
    (harness / "alignment.yaml").write_text(yaml.safe_dump(document))
    validate_sealed_freeze(
        harness,
        document,
        decisions=[],
        boundary_refs={"interface": [], "permission": [], "persistence": []},
        bootstrap_legacy_off=True,
        architecture_facts=ArchitectureFreezeFacts("off", None, ()),
    )

    result = cli(path, "align", "check")

    assert result.returncode == 1
    assert "ALIGNMENT_BLOCKED" in result.stderr
    assert "LOOP-001: OPEN_LOOP" in result.stderr
    assert "Next:" in result.stderr

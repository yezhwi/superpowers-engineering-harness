"""Milestone 2: Deterministic Quality Gate tests.

Covers:
1. missing evidence -> BLOCKED
2. stale evidence -> BLOCKED
3. major finding -> BLOCKED
4. unverified requirement -> BLOCKED
5. violated invariant -> BLOCKED
6. all conditions satisfied -> PASS (exit 0)
plus INVALID_HARNESS_STATE (exit 2) cases.
"""

import hashlib
import json
import os
from importlib import resources
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from evidence_factory import write_evidence

REPO = Path(__file__).resolve().parent.parent
SAFE_DIMENSIONS = {
    "scope": "low",
    "contract": "none",
    "data": "none",
    "authorization": "none",
    "security": "none",
    "concurrency": "none",
    "deployment": "none",
}

HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO
).stdout.strip()


def _gate(harness_dir: Path):
    from harness.quality_gate import InvalidHarnessState, assess_gate

    try:
        assessment = assess_gate(harness_dir)
    except InvalidHarnessState as exc:
        return subprocess.CompletedProcess([], 2, "", f"INVALID_HARNESS_STATE: {exc}\n")
    if assessment.status == "PASS":
        return subprocess.CompletedProcess([], 0, "QUALITY GATE: PASS\n", "")
    output = "QUALITY GATE: BLOCKED\n\nBlocking:\n" + "".join(
        f"- {blocker.message}\n" for blocker in assessment.blockers
    )
    return subprocess.CompletedProcess([], 1, output, "")


def make_harness(tmp_path: Path) -> Path:
    """Build a fully passing harness dir; individual tests break one thing."""
    h = tmp_path / ".harness"

    task = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    task['task']['id'] = 'TASK-001'
    task["state"] = "GATING"
    h.mkdir(parents=True)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    gate_cfg = yaml.safe_load(
        resources.files("harness").joinpath("templates", "gate.yaml").read_text()
    )
    (h / "gate.yaml").write_text(yaml.safe_dump(gate_cfg))

    requirements = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "verified",
                "evidence": ["build.json"],
                "test_plan": {
                    "strategies": ["manual"],
                    "cases": [
                        {
                            "id": "TC-002",
                            "type": "regression",
                            "strategy": "manual",
                            "description": "verify works",
                            "tests": [],
                        }
                    ],
                },
            },
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))

    invariants = {
        "invariants": [
            {
                "id": "INV-001",
                "statement": "safe",
                "category": "correctness",
                "severity": "critical",
                "status": "verified",
                "verification": ["build.json"],
                "test_plan": {
                    "strategies": ["manual"],
                    "cases": [
                        {
                            "id": "TC-101",
                            "type": "invariant",
                            "strategy": "manual",
                            "description": "verify safe",
                            "tests": [],
                        }
                    ],
                },
            },
        ]
    }
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))

    evidence_dir = h / "evidence"
    evidence_dir.mkdir()
    for etype in ("build", "unit_test"):
        write_evidence(REPO, h, etype)
    build_evidence = json.loads((evidence_dir / "build.json").read_text())
    build_evidence["covered_test_cases"] = ["TC-002", "TC-101"]
    (evidence_dir / "build.json").write_text(json.dumps(build_evidence))
    review = json.loads((evidence_dir / "build.json").read_text())
    review["type"] = "review"
    review["checks"] = {
        name: {"result": "not_applicable", "evidence": "fixture"}
        for name in ("delete", "reuse", "stdlib", "native", "yagni", "shrink")
    }
    review["review_scope"] = {"files": []}
    (evidence_dir / "complexity-review.json").write_text(json.dumps(review))

    findings_dir = h / "findings"
    findings_dir.mkdir()

    from test_test_scope import initialize_test_origin

    initialize_test_origin(h, [])
    return h


def _enable_standard_plan(h: Path) -> Path:
    from harness.plan_reconciliation import plan_fingerprint

    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"] = {
        "level": "Q2",
        "profile": "STANDARD",
        "dimensions": SAFE_DIMENSIONS,
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
    }
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "finish"}]}
    (h / "plan.yaml").write_text(yaml.safe_dump(plan))
    (h / "plan-execution.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "plan": {
                    "path": ".harness/plan.yaml",
                    "fingerprint": plan_fingerprint(plan),
                },
                "items": {"P-001": {"status": "PENDING"}},
            }
        )
    )
    return task_path


def test_enabled_gate_emits_plan_item_unreconciled_blocker(tmp_path, monkeypatch):
    from harness import quality_gate
    from harness.plan_reconciliation import plan_fingerprint
    from harness.quality_gate import run_gate

    monkeypatch.setattr(quality_gate, "_append_live_alignment_drift", lambda *args: None)

    h = make_harness(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"] = {
        "level": "Q2",
        "profile": "STANDARD",
        "dimensions": SAFE_DIMENSIONS,
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
    }
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "finish"}]}
    (h / "plan.yaml").write_text(yaml.safe_dump(plan))
    (h / "plan-execution.yaml").write_text(
        yaml.safe_dump(
            {"version": 1, "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint(plan)}, "items": {"P-001": {"status": "PENDING"}}}
        )
    )

    status, blockers = run_gate(h)

    assert status == "BLOCKED"
    assert [(blocker.code, blocker.source, blocker.recover_to) for blocker in blockers if blocker.code.startswith("PLAN_")] == [
        ("PLAN_ITEM_UNRECONCILED", "P-001", "IMPLEMENTING")
    ]


def test_enabled_plan_keeps_malformed_decision_in_blocked_gate_domain(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from harness import controlplane, quality_gate

    monkeypatch.setattr(quality_gate, "_append_live_alignment_drift", lambda *args: None)
    h = make_harness(tmp_path)
    task_path = _enable_standard_plan(h)
    decisions = h / "decisions"
    decisions.mkdir()
    (decisions / "DEC-001.yaml").write_text("not: a-valid-decision\n")

    current_workspace = quality_gate.snapshot().fingerprint
    monkeypatch.setattr(quality_gate, "git_head", lambda: HEAD)
    monkeypatch.setattr(
        quality_gate,
        "snapshot",
        lambda: SimpleNamespace(fingerprint=current_workspace),
    )
    monkeypatch.chdir(tmp_path)
    assert controlplane.cmd_gate() == 0

    persisted_task = yaml.safe_load(task_path.read_text())
    assert persisted_task["state"] == "BLOCKED"
    assert [
        blocker["code"]
        for blocker in persisted_task["gate"]["blocked_by"]
        if blocker["code"] == "DECISION_REFERENCE_INVALID"
    ] == ["DECISION_REFERENCE_INVALID"]


def test_enabled_plan_adds_decision_blocker_when_only_plan_load_fails(
    tmp_path, monkeypatch
):
    from harness import quality_gate
    from harness.decision import DecisionError

    monkeypatch.setattr(quality_gate, "_append_live_alignment_drift", lambda *args: None)
    h = make_harness(tmp_path)
    _enable_standard_plan(h)

    def decision_failure(*_args, **_kwargs):
        raise DecisionError("DECISION_RECORD_INVALID")

    monkeypatch.setattr(
        quality_gate, "assess_plan_reconciliation_documents", decision_failure
    )

    result = quality_gate.assess_gate(h)

    assert [
        blocker.code
        for blocker in result.blockers
        if blocker.code == "DECISION_REFERENCE_INVALID"
    ] == ["DECISION_REFERENCE_INVALID"]


def test_enabled_plan_maps_workspace_error_to_invalid_harness_state(
    tmp_path, monkeypatch
):
    from harness import plan_automation, quality_gate
    from harness.quality_gate import InvalidHarnessState
    from harness.workspace import WorkspaceError

    monkeypatch.setattr(quality_gate, "_append_live_alignment_drift", lambda *args: None)
    h = make_harness(tmp_path)
    _enable_standard_plan(h)

    def workspace_failure(*_args, **_kwargs):
        raise WorkspaceError("PLAN_WORKSPACE_QUERY_FAILED")

    monkeypatch.setattr(plan_automation, "mechanical_surface_facts", workspace_failure)

    with pytest.raises(InvalidHarnessState, match="PLAN_WORKSPACE_QUERY_FAILED"):
        quality_gate.assess_gate(h)


def test_gate_computes_one_plan_assessment_and_carries_same_object(tmp_path, monkeypatch):
    from harness import quality_gate
    from harness.plan_reconciliation import plan_fingerprint

    monkeypatch.setattr(quality_gate, "_append_live_alignment_drift", lambda *args: None)
    h = make_harness(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"] = {
        "level": "Q2",
        "profile": "STANDARD",
        "dimensions": SAFE_DIMENSIONS,
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
    }
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "finish"}]}
    (h / "plan.yaml").write_text(yaml.safe_dump(plan))
    (h / "plan-execution.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "plan": {
                    "path": ".harness/plan.yaml",
                    "fingerprint": plan_fingerprint(plan),
                },
                "items": {"P-001": {"status": "PENDING"}},
            }
        )
    )
    original_load = quality_gate.load_plan_artifacts
    original_assess = quality_gate.assess_plan_reconciliation_documents
    calls = {"load": 0, "assess": 0}
    captured = []

    def load_once(*args, **kwargs):
        calls["load"] += 1
        return original_load(*args, **kwargs)

    def assess_once(*args, **kwargs):
        calls["assess"] += 1
        result = original_assess(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(quality_gate, "load_plan_artifacts", load_once)
    monkeypatch.setattr(
        quality_gate, "assess_plan_reconciliation_documents", assess_once
    )
    monkeypatch.setattr(
        quality_gate,
        "validate_plan_reconciliation",
        lambda *_args, **_kwargs: pytest.fail("legacy wrapper must not run"),
        raising=False,
    )

    result = quality_gate.assess_gate(h)

    assert calls == {"load": 1, "assess": 1}
    assert result.plan_assessment is captured[0]
    plan_blocker = next(blocker for blocker in result.blockers if blocker.code.startswith("PLAN_"))
    assert plan_blocker is captured[0].blockers[0]


def test_fast_gate_ignores_ad_hoc_enablement_and_malformed_plan(tmp_path):
    from harness.quality_gate import run_gate

    h = make_harness(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"] = {
        "level": "Q1",
        "profile": "FAST",
        "dimensions": SAFE_DIMENSIONS,
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
    }
    task["plan_reconciliation"] = {"enabled": True, "mode": "task_and_final"}
    task["git"] = {"head": HEAD, "base_commit": HEAD}
    from harness.workspace import protected_paths_fingerprint

    task["risk"]["user_changes"]["fingerprint"] = protected_paths_fingerprint(())
    task_path.write_text(yaml.safe_dump(task))
    (h / "plan.yaml").write_text("[")
    (h / "plan-execution.yaml").write_text("[")

    status, blockers = run_gate(h)

    assert status in {"PASS", "BLOCKED"}
    assert not [blocker for blocker in blockers if blocker.code.startswith("PLAN_")]


def test_gate_unions_fresh_related_test_evidence(tmp_path):
    from harness.quality_gate import run_gate

    h = make_harness(tmp_path)
    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["test_plan"] = {
        "strategies": ["unit"],
        "cases": [
            {"id": "TC-002", "type": "regression", "strategy": "unit", "description": "A", "tests": ["tests/test_quality_gate.py"]},
            {"id": "TC-003", "type": "regression", "strategy": "unit", "description": "B", "tests": ["tests/test_evidence.py"]},
        ],
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    base = json.loads((h / "evidence" / "unit-test.json").read_text())
    for name, target in (("unit-test-a.json", "tests/test_quality_gate.py"), ("unit-test-b.json", "tests/test_evidence.py")):
        test_path = tmp_path / target
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text("def test_ok():\n    pass\n")
        record = {**base, "scope": "related", "covered_tests": [target], "command": f"pytest {target}"}
        (h / "evidence" / name).write_text(json.dumps(record))
    (h / "evidence" / "unit-test.json").unlink()

    status, blockers = run_gate(h)

    assert status == "PASS", blockers


def test_standalone_quality_gate_is_disabled_without_state_write(tmp_path):
    h = make_harness(tmp_path)
    before = (h / "current-task.yaml").read_bytes()
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "quality_gate.py"), "--harness-dir", str(h)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 2
    assert "DEPRECATED: use harness gate" in result.stderr
    assert (h / "current-task.yaml").read_bytes() == before


def test_requirement_evidence_reference_cannot_escape_evidence_directory(tmp_path):
    from harness.quality_gate import run_gate

    h = make_harness(tmp_path)
    escaped = tmp_path / "escaped.json"
    escaped.write_bytes((h / "evidence" / "build.json").read_bytes())
    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["evidence"] = [str(escaped)]
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))

    status, blockers = run_gate(h)

    assert status == "BLOCKED"
    assert any(blocker.code == "EVIDENCE_MISSING" for blocker in blockers)


def test_gate_rejects_removed_must_match_head_override(tmp_path):
    from harness.quality_gate import InvalidHarnessState, run_gate

    h = make_harness(tmp_path)
    config = yaml.safe_load((h / "gate.yaml").read_text())
    config["gate"]["evidence"] = {"must_match_head": False}
    (h / "gate.yaml").write_text(yaml.safe_dump(config))

    with pytest.raises(InvalidHarnessState, match="gate.schema.json"):
        run_gate(h)


def test_gate_rejects_open_finding_allowance_override(tmp_path):
    from harness.quality_gate import InvalidHarnessState, run_gate

    h = make_harness(tmp_path)
    config = yaml.safe_load((h / "gate.yaml").read_text())
    config["gate"]["findings"]["critical_allowed"] = 1
    (h / "gate.yaml").write_text(yaml.safe_dump(config))

    with pytest.raises(InvalidHarnessState, match="gate.schema.json"):
        run_gate(h)


def test_gate_rejects_invalid_configuration_value(tmp_path):
    from harness.quality_gate import InvalidHarnessState, run_gate

    h = make_harness(tmp_path)
    config = yaml.safe_load((h / "gate.yaml").read_text())
    config["gate"]["findings"]["critical_allowed"] = -1
    (h / "gate.yaml").write_text(yaml.safe_dump(config))

    with pytest.raises(InvalidHarnessState, match="gate.schema.json"):
        run_gate(h)


def test_schema_resource_failure_stays_in_gate_error_domain(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.quality_gate import InvalidHarnessState, validate_schema

    h = make_harness(tmp_path)
    with pytest.raises(InvalidHarnessState, match="cannot load") as caught:
        validate_schema({}, "unknown.schema.json", h / "gate.yaml")
    assert not isinstance(caught.value, ContextBuildError)


def test_gate_cli_maps_context_source_errors_to_invalid_harness_state(
    tmp_path, monkeypatch, capsys
):
    from harness import controlplane, schema_resources
    from harness.context.model import ContextBuildError

    make_harness(tmp_path)
    monkeypatch.chdir(tmp_path)

    def boom(name):
        raise ContextBuildError(
            "CONTEXT_REFERENCE_BROKEN", "unregistered schema resource"
        )

    monkeypatch.setattr(schema_resources, "read_schema", boom)
    assert controlplane.cmd_gate() == 2
    captured = capsys.readouterr()
    assert "INVALID_HARNESS_STATE" in captured.err
    assert captured.out == ""


def test_task_schema_rejects_incompatible_risk_level_and_profile(tmp_path):
    from harness.quality_gate import InvalidHarnessState, validate_schema

    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["risk"] = {
        "level": "Q3",
        "profile": "FAST",
        "dimensions": {
            name: "low" if name == "scope" else "none"
            for name in (
                "scope",
                "contract",
                "data",
                "authorization",
                "security",
                "concurrency",
                "deployment",
            )
        },
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": ""},
    }

    with pytest.raises(InvalidHarnessState, match="risk.profile"):
        validate_schema(task, "task.schema.json", h / "current-task.yaml")


def test_gate_rejects_incompatible_risk_level_and_profile(tmp_path):
    from harness.quality_gate import InvalidHarnessState, run_gate

    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["risk"] = {
        "level": "Q3",
        "profile": "FAST",
        "dimensions": {
            name: "low" if name == "scope" else "none"
            for name in (
                "scope",
                "contract",
                "data",
                "authorization",
                "security",
                "concurrency",
                "deployment",
            )
        },
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": ""},
    }
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    with pytest.raises(InvalidHarnessState, match="risk.profile"):
        run_gate(h)


def test_fast_gate_requires_build_by_default(tmp_path):
    from harness.workspace import protected_paths_fingerprint

    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["git"]["base_commit"] = HEAD
    (h / "risk-boundaries.yaml").write_text(
        "boundaries:\n  q2: [never/**]\n  q3: [never/**]\n"
    )
    task["risk"] = {
        "level": "Q1",
        "profile": "FAST",
        "dimensions": {
            "scope": "low",
            "contract": "none",
            "data": "none",
            "authorization": "none",
            "security": "none",
            "concurrency": "none",
            "deployment": "none",
        },
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": protected_paths_fingerprint(())},
    }
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    (h / "requirements.yaml").unlink()
    (h / "invariants.yaml").unlink()
    write_evidence(REPO, h, "unit_test", exit_code=1, name="fast-red-unit-test.json")
    write_evidence(REPO, h, "unit_test", name="fast-green-unit-test.json")
    (h / "evidence" / "build.json").unlink()

    status, blockers = __import__(
        "harness.quality_gate", fromlist=["run_gate"]
    ).run_gate(h)

    assert status == "BLOCKED"
    assert any(item.code == "FAST_REPOSITORY_VERIFICATION_MISSING" for item in blockers)


def test_fast_gate_requires_only_task_phase_proof(tmp_path):
    from harness.workspace import protected_paths_fingerprint

    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["git"]["base_commit"] = HEAD
    (h / "risk-boundaries.yaml").write_text(
        "boundaries:\n  q2: [never/**]\n  q3: [never/**]\n"
    )
    task["risk"] = {
        "level": "Q1",
        "profile": "FAST",
        "dimensions": {
            "scope": "low",
            "contract": "none",
            "data": "none",
            "authorization": "none",
            "security": "none",
            "concurrency": "none",
            "deployment": "none",
        },
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": protected_paths_fingerprint(())},
    }
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    (h / "requirements.yaml").unlink()
    (h / "invariants.yaml").unlink()
    write_evidence(REPO, h, "unit_test", exit_code=1, name="fast-red-unit-test.json")
    write_evidence(REPO, h, "unit_test", name="fast-green-unit-test.json")

    status, blockers = __import__(
        "harness.quality_gate", fromlist=["run_gate"]
    ).run_gate(h)

    assert status == "PASS"
    assert blockers == []


def test_fast_gate_blocks_business_change_without_risk_policy(tmp_path, monkeypatch):
    from harness.quality_gate import run_fast_gate
    from harness.workspace import git_head, protected_paths_fingerprint, snapshot

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "base.txt").write_text("base\n")
    subprocess.run(["git", "add", "base.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = git_head(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/api.py").write_text("changed\n")
    monkeypatch.chdir(tmp_path)
    h = tmp_path / ".harness"
    (h / "evidence").mkdir(parents=True)
    task = {
        "git": {"base_commit": base},
        "risk": {
            "level": "Q1",
            "user_changes": {
                "paths": [],
                "fingerprint": protected_paths_fingerprint(()),
            },
        },
    }

    status, blockers = run_fast_gate(task, h, git_head(), snapshot().fingerprint)

    assert status == "BLOCKED"
    assert blockers[0].code == "RISK_REVALIDATION_POLICY_MISSING"


def test_fast_gate_blocks_modified_preexisting_user_change(tmp_path, monkeypatch):
    from harness.quality_gate import run_fast_gate
    from harness.workspace import git_head, protected_paths_fingerprint, snapshot

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "user.txt").write_text("base\n")
    subprocess.run(["git", "add", "user.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    (tmp_path / "user.txt").write_text("user work\n")
    monkeypatch.chdir(tmp_path)
    h = tmp_path / ".harness"
    (h / "evidence").mkdir(parents=True)
    paths = ("user.txt",)
    (h / "risk-boundaries.yaml").write_text(
        "boundaries:\n  q2: [never/**]\n  q3: [never/**]\n"
    )
    task = {
        "git": {"base_commit": git_head()},
        "risk": {
            "level": "Q1",
            "user_changes": {
                "paths": list(paths),
                "fingerprint": protected_paths_fingerprint(paths),
            },
        },
    }
    write_evidence(
        tmp_path, h, "unit_test", exit_code=1, name="fast-red-unit-test.json"
    )
    write_evidence(tmp_path, h, "unit_test", name="fast-green-unit-test.json")
    (tmp_path / "user.txt").write_text("overwritten\n")

    status, blockers = run_fast_gate(task, h, git_head(), snapshot().fingerprint)

    assert status == "BLOCKED"
    assert blockers[0].code == "FAST_USER_CHANGE_MODIFIED"


def test_all_conditions_pass(tmp_path):
    h = make_harness(tmp_path)
    result = _gate(h)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "QUALITY GATE: PASS" in result.stdout


def test_required_complexity_review_missing_blocks(tmp_path):
    h = make_harness(tmp_path)
    gate_cfg = yaml.safe_load((h / "gate.yaml").read_text())
    gate_cfg["gate"]["complexity"] = {"required": True, "blocking": ["high"]}
    (h / "gate.yaml").write_text(yaml.safe_dump(gate_cfg))
    (h / "evidence" / "complexity-review.json").unlink()

    result = _gate(h)

    assert result.returncode == 1
    assert "missing complexity-review evidence" in result.stdout


@pytest.mark.parametrize("severity", ["medium", "low"])
def test_open_nonblocking_complexity_finding_does_not_block(tmp_path, severity):
    h = make_harness(tmp_path)
    finding = {
        "id": "CPLX-001",
        "category": "complexity",
        "type": "shrink",
        "severity": severity,
        "status": "open",
        "location": {"file": "x.py"},
        "summary": "simplify",
        "reason": "primitive exists",
        "evidence": {"primitive": "x"},
        "recommendation": "use primitive",
    }
    (h / "findings" / "CPLX-001.yaml").write_text(yaml.safe_dump(finding))

    assert _gate(h).returncode == 0


def test_accepted_high_complexity_finding_does_not_block(tmp_path):
    h = make_harness(tmp_path)
    finding = {
        "id": "CPLX-001",
        "category": "complexity",
        "type": "yagni",
        "severity": "high",
        "status": "accepted",
        "location": {"file": "x.py"},
        "summary": "compatibility layer",
        "reason": "v1 API",
        "evidence": {"requirement": "REQ-017"},
        "recommendation": "keep layer",
        "acceptance_reason": "REQ-017 compatibility",
    }
    (h / "findings" / "CPLX-001.yaml").write_text(yaml.safe_dump(finding))

    assert _gate(h).returncode == 0


def test_open_high_complexity_finding_blocks(tmp_path):
    h = make_harness(tmp_path)
    finding = {
        "id": "CPLX-001",
        "category": "complexity",
        "type": "reuse",
        "severity": "high",
        "status": "open",
        "location": {"file": "x.py"},
        "summary": "duplicate",
        "reason": "x exists",
        "evidence": {"candidate": "x"},
        "recommendation": "reuse x",
    }
    (h / "findings" / "CPLX-001.yaml").write_text(yaml.safe_dump(finding))

    result = _gate(h)
    assert result.returncode == 1
    assert "High complexity finding CPLX-001 is open" in result.stdout


def test_gate_writes_back_status(tmp_path):
    from harness.quality_gate import assess_gate, write_back

    h = make_harness(tmp_path)
    write_back(h, assess_gate(h))
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    assert task["gate"]["status"] == "PASS"
    assert task["git"]["head"] == HEAD


# 1. missing evidence -------------------------------------------------------


def test_gate_write_back_preserves_task_git_baseline(tmp_path):
    """Break caught: a Gate observation overwrites immutable task review baseline."""
    h = make_harness(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["git"]["base_commit"] = "b" * 40
    task_path.write_text(yaml.safe_dump(task))

    from harness.quality_gate import assess_gate, write_back

    write_back(h, assess_gate(h))

    persisted = yaml.safe_load(task_path.read_text())
    assert persisted["git"] == {"base_commit": "b" * 40, "head": HEAD}


def test_blocked_gate_write_back_preserves_task_git_baseline(tmp_path):
    """Break caught: recovery loop loses baseline only when Gate blocks."""
    h = make_harness(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["git"]["base_commit"] = "b" * 40
    task_path.write_text(yaml.safe_dump(task))
    (h / "evidence" / "build.json").unlink()

    result = _gate(h)

    assert result.returncode == 1
    assert yaml.safe_load(task_path.read_text())["git"]["base_commit"] == "b" * 40


@pytest.mark.parametrize("missing", ["build", "unit-test"])
def test_missing_evidence_blocked(tmp_path, missing):
    h = make_harness(tmp_path)
    (h / "evidence" / f"{missing}.json").unlink()
    result = _gate(h)
    assert result.returncode == 1
    assert "BLOCKED" in result.stdout
    assert "missing" in result.stdout


def test_failed_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    ev = json.loads((h / "evidence" / "build.json").read_text())
    ev["exit_code"] = 2
    (h / "evidence" / "build.json").write_text(json.dumps(ev))
    result = _gate(h)
    assert result.returncode == 1
    assert "EVIDENCE_RESULT_MISMATCH" in result.stdout


def test_optional_verification_not_required(tmp_path):
    h = make_harness(tmp_path)
    # integration_test is optional in template; no evidence for it -> still PASS
    assert _gate(h).returncode == 0


# 2. stale evidence ---------------------------------------------------------


def test_stale_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    ev = json.loads((h / "evidence" / "unit-test.json").read_text())
    ev["commit"] = "0" * 40
    (h / "evidence" / "unit-test.json").write_text(json.dumps(ev))
    result = _gate(h)
    assert result.returncode == 1
    assert "EVIDENCE_HEAD_MISMATCH" in result.stdout


def test_stale_evidence_via_real_collection(tmp_path):
    """End-to-end: fresh evidence collected, then HEAD moves -> stale."""
    h = make_harness(tmp_path)
    # overwrite build evidence with commit from an older fake sha
    (h / "evidence" / "build.json").write_text(
        json.dumps(
            {
                "type": "build",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "command": "true",
                "exit_code": 0,
                "commit": "deadbeef",
            }
        )
    )
    result = _gate(h)
    assert result.returncode == 1
    assert "EVIDENCE_HEAD_MISMATCH" in result.stdout


# 3. major finding ----------------------------------------------------------


def finding_doc(fid, severity, status, **extra):
    finding = {
        "id": fid,
        "category": "adversarial",
        "kind": "failure_scenario",
        "target": "REQ-001",
        "scenario": "concrete attack scenario",
        "severity": severity,
        "status": status,
    }
    finding.update(extra)
    return finding


def test_major_finding_blocked(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0001", "major", "PROPOSED")
    (h / "findings" / "FND-0001.yaml").write_text(yaml.safe_dump(finding))
    result = _gate(h)
    assert result.returncode == 1
    assert "Major finding FND-0001" in result.stdout


def test_critical_finding_blocked(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0002", "critical", "PROPOSED")
    (h / "findings" / "FND-0002.yaml").write_text(yaml.safe_dump(finding))
    result = _gate(h)
    assert result.returncode == 1
    assert "Critical finding FND-0002" in result.stdout


def test_assess_gate_is_side_effect_free_and_matches_run_gate(tmp_path):
    from harness.quality_gate import assess_gate, run_gate

    h = make_harness(tmp_path)
    before = (h / "current-task.yaml").read_bytes()
    assessment = assess_gate(h, allow_preflight=True)

    assert (assessment.status, list(assessment.blockers)) == run_gate(
        h, allow_preflight=True
    )
    assert (h / "current-task.yaml").read_bytes() == before
    assert assessment.quality["status"] == assessment.status
    assert assessment.release_readiness["status"] in {
        "READY",
        "DRAFT_ONLY",
        "NOT_READY",
    }


def test_write_back_persists_assessment_without_recomputing_readiness(tmp_path):
    from harness.quality_gate import assess_gate, write_back

    h = make_harness(tmp_path)
    assessment = assess_gate(h, allow_preflight=True)
    write_back(h, assessment)
    task = yaml.safe_load((h / "current-task.yaml").read_text())

    assert task["gate"]["quality"] == assessment.quality
    assert task["gate"]["release_readiness"] == assessment.release_readiness


def test_closed_findings_do_not_block(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc(
        "FND-0003", "major", "REJECTED", attempts=["x"], rejection_reason="impossible"
    )
    (h / "findings" / "FND-0003.yaml").write_text(yaml.safe_dump(finding))
    assert _gate(h).returncode == 0


def test_confirmed_finding_without_regression_test_blocked(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0004", "minor", "CONFIRMED")
    (h / "findings" / "FND-0004.yaml").write_text(yaml.safe_dump(finding))
    result = _gate(h)
    assert result.returncode == 2
    assert "finding.schema.json" in result.stderr


def test_confirmed_finding_with_regression_test_ok(tmp_path):
    h = make_harness(tmp_path)
    finding = finding_doc(
        "FND-0005",
        "minor",
        "CONFIRMED",
        regression_test={"path": "tests/test_fix.py"},
    )
    (h / "findings" / "FND-0005.yaml").write_text(yaml.safe_dump(finding))
    # CONFIRMED without red_evidence is schema-invalid, never merely open.
    assert _gate(h).returncode == 2


# 4. unverified requirement -------------------------------------------------


def test_unverified_requirement_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = yaml.safe_load((h / "requirements.yaml").read_text())
    reqs["requirements"][0]["status"] = "implemented"
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = _gate(h)
    assert result.returncode == 1
    assert "REQ-001 not verified" in result.stdout


def test_should_requirement_without_test_plan_blocks(tmp_path):
    h = make_harness(tmp_path)
    reqs = yaml.safe_load((h / "requirements.yaml").read_text())
    reqs["requirements"].append(
        {
            "id": "REQ-002",
            "statement": "nice",
            "priority": "should",
            "status": "pending",
            "evidence": [],
        }
    )
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    assert _gate(h).returncode == 1


# 5. violated invariant -----------------------------------------------------


def test_violated_invariant_blocked(tmp_path):
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "violated"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    result = _gate(h)
    assert result.returncode == 1
    assert "INV-001 violated" in result.stdout


def test_violated_invariant_emits_implementation_reason_code(tmp_path):
    from harness.quality_gate import run_gate

    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "violated"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))

    status, blockers = run_gate(h)

    assert status == "BLOCKED"
    assert blockers[0].code == "INVARIANT_VIOLATED"
    assert blockers[0].category == "implementation"


def test_unproven_invariant_retains_verification_reason_code(tmp_path):
    from harness.quality_gate import run_gate

    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))

    status, blockers = run_gate(h)

    assert status == "BLOCKED"
    assert blockers[0].code == "INVARIANT_UNVERIFIED"
    assert blockers[0].category == "verification"


def test_pending_critical_invariant_blocks(tmp_path):
    # pending = not proven = BLOCKED for critical/major (review fix #6)
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    result = _gate(h)
    assert result.returncode == 1
    assert "not verified" in result.stdout


def test_pending_major_invariant_blocks(tmp_path):
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["severity"] = "major"
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    assert _gate(h).returncode == 1


def test_pending_minor_invariant_passes_by_default(tmp_path):
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["severity"] = "minor"
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    assert _gate(h).returncode == 0


def test_pending_minor_invariant_blocks_when_policy_requires(tmp_path):
    h = make_harness(tmp_path)
    gate_cfg = yaml.safe_load((h / "gate.yaml").read_text())
    gate_cfg["gate"]["invariants"]["minor_verified"] = True
    (h / "gate.yaml").write_text(yaml.safe_dump(gate_cfg))
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["severity"] = "minor"
    inv["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    assert _gate(h).returncode == 1


# INVALID_HARNESS_STATE (exit 2) ---------------------------------------------


def test_missing_current_task_invalid(tmp_path):
    h = tmp_path / ".harness"
    h.mkdir()
    result = _gate(h)
    assert result.returncode == 2


def test_wrong_state_invalid(tmp_path):
    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["state"] = "IMPLEMENTING"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    result = _gate(h)
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr


def test_missing_requirements_file_invalid(tmp_path):
    h = make_harness(tmp_path)
    (h / "requirements.yaml").unlink()
    assert _gate(h).returncode == 2


def test_bad_evidence_json_invalid(tmp_path):
    h = make_harness(tmp_path)
    (h / "evidence" / "unit-test.json").write_text("{not json")
    assert _gate(h).returncode == 2


def test_malformed_finding_invalid(tmp_path):
    h = make_harness(tmp_path)
    (h / "findings" / "F-BAD.yaml").write_text("{not valid yaml")
    result = _gate(h)
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr


def test_multiple_blockers_listed(tmp_path):
    h = make_harness(tmp_path)
    reqs = yaml.safe_load((h / "requirements.yaml").read_text())
    reqs["requirements"][0]["status"] = "pending"
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    (h / "evidence" / "build.json").unlink()
    finding = finding_doc("FND-0009", "major", "PROPOSED")
    (h / "findings" / "FND-0009.yaml").write_text(yaml.safe_dump(finding))

    out = _gate(h)
    assert out.returncode == 1
    stdout = out.stdout
    assert "REQ-001 not verified" in stdout
    assert "missing build evidence" in stdout
    assert "Major finding FND-0009" in stdout


# Requirement evidence validation (review fix #5) -----------------------------


def test_verified_requirement_without_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "verified",
                "evidence": [],
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = _gate(h)
    assert result.returncode == 1
    assert "verified without evidence" in result.stdout


def test_verified_requirement_missing_evidence_file_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "verified",
                "evidence": ["nope.json"],
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    assert "evidence missing" in _gate(h).stdout


def test_verified_requirement_stale_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "verified",
                "evidence": ["build.json"],
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    ev = json.loads((h / "evidence" / "build.json").read_text())
    ev["commit"] = "0" * 40
    (h / "evidence" / "build.json").write_text(json.dumps(ev))
    assert "EVIDENCE_HEAD_MISMATCH" in _gate(h).stdout


def test_verified_requirement_failed_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "must",
                "status": "verified",
                "evidence": ["build.json"],
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    ev = json.loads((h / "evidence" / "build.json").read_text())
    ev["exit_code"] = 3
    (h / "evidence" / "build.json").write_text(json.dumps(ev))
    assert "EVIDENCE_RESULT_MISMATCH" in _gate(h).stdout


def test_should_requirement_without_test_plan_blocks_even_if_verified(tmp_path):
    h = make_harness(tmp_path)
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "works",
                "priority": "should",
                "status": "verified",
                "evidence": [],
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    assert _gate(h).returncode == 1


def test_violated_invariant_blocks_even_if_allowance_configured(tmp_path):
    # No tolerance knob exists: unsupported policy fails closed before Gate.
    h = make_harness(tmp_path)
    gate_cfg = yaml.safe_load((h / "gate.yaml").read_text())
    gate_cfg["gate"]["invariants"]["violated_allowed"] = 5
    (h / "gate.yaml").write_text(yaml.safe_dump(gate_cfg))
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["status"] = "violated"
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    result = _gate(h)
    assert result.returncode == 2
    assert "gate.schema.json" in result.stderr


# Schema validation: fail closed (CR-001 P0) ---------------------------------


def test_requirement_missing_priority_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    reqs = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "must not duplicate side effects",
                "status": "pending",
                "evidence": [],
            }
        ]
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(reqs))
    result = _gate(h)
    assert result.returncode == 2
    assert "fails requirement.schema.json" in result.stderr
    assert "priority" in result.stderr


def test_invariant_missing_severity_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    invs = {
        "invariants": [
            {
                "id": "INV-001",
                "statement": "at most one side effect",
                "category": "idempotency",
                "status": "pending",
                "verification": ["build.json"],
            }
        ]
    }
    (h / "invariants.yaml").write_text(yaml.safe_dump(invs))
    result = _gate(h)
    assert result.returncode == 2
    assert "fails invariant.schema.json" in result.stderr
    assert "severity" in result.stderr


def test_finding_missing_lifecycle_fields_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    # Gate must reject this malformed record before deciding its severity.
    (h / "findings" / "fnd-001.yaml").write_text(
        yaml.safe_dump({"id": "FND-001", "severity": "major", "status": "PROPOSED"})
    )
    result = _gate(h)
    assert result.returncode == 2
    assert "MIGRATION_REQUIRED" in result.stderr


def test_evidence_missing_commit_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    evidence = json.loads((h / "evidence" / "build.json").read_text())
    del evidence["commit"]
    (h / "evidence" / "build.json").write_text(json.dumps(evidence))
    result = _gate(h)
    assert result.returncode == 2
    assert "fails evidence.schema.json" in result.stderr


def test_direct_verified_status_edit_without_proof_is_invalid(tmp_path):
    """P0: status-only YAML edit cannot turn a critical finding healthy."""
    h = make_harness(tmp_path)
    finding = finding_doc("FND-0999", "critical", "VERIFIED")
    (h / "findings" / "fnd-0999.yaml").write_text(yaml.safe_dump(finding))
    result = _gate(h)
    assert result.returncode == 2
    assert "finding.schema.json" in result.stderr


def test_verified_critical_invariant_without_evidence_blocked(tmp_path):
    h = make_harness(tmp_path)
    inv = yaml.safe_load((h / "invariants.yaml").read_text())
    inv["invariants"][0]["verification"] = []
    (h / "invariants.yaml").write_text(yaml.safe_dump(inv))
    result = _gate(h)
    assert result.returncode == 1
    assert "verified without verification evidence" in result.stdout


def test_gate_returns_typed_evidence_blocker(tmp_path):
    from harness.blockers import GateBlocker
    from harness.quality_gate import run_gate

    h = make_harness(tmp_path)
    (h / "evidence" / "build.json").unlink()

    status, blockers = run_gate(h)

    assert status == "BLOCKED"
    assert any(
        blocker
        == GateBlocker(
            "EVIDENCE_MISSING",
            "verification",
            "missing build evidence",
            source="build",
            recover_to="VERIFYING",
        )
        for blocker in blockers
    )


def test_gate_from_reviewing_is_invalid_harness_state(tmp_path):
    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["state"] = "REVIEWING"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    result = _gate(h)
    assert result.returncode == 2
    assert "must be GATING" in result.stderr


def test_candidate_gate_receipt_binds_qualified_execution_domain():
    from harness.candidate_assessment import CandidateAssessmentView

    view = CandidateAssessmentView("sha256:" + "1" * 64, "a" * 40, "b" * 40, "sha256:" + "2" * 64, ("src/a.py",), (".harness/evidence/candidate-proof/deep/proof.json",))
    assert view.domain == "harness:candidate-assessment:v1"
    assert view.evidence_refs == (".harness/evidence/candidate-proof/deep/proof.json",)


def test_default_gate_and_legacy_evidence_remain_head_bound():
    from harness.candidate_assessment import CandidateAssessmentView
    import inspect
    from harness import quality_gate

    assert "candidate" not in inspect.signature(quality_gate.assess_gate).parameters
    assert CandidateAssessmentView.__dataclass_fields__["domain"].default == "harness:candidate-assessment:v1"


def test_candidate_acceptance_is_derived_from_one_original_gate_assessment(tmp_path):
    """Frozen INV-001 entry: real proofs/reviews cannot waive original pending-REQ blocker."""
    from test_cli_task_recovery import _exercise_candidate_workflow

    _exercise_candidate_workflow(tmp_path, gate_defect=True)


def test_candidate_acceptance_refuses_exit0_claims_without_valid_preparation(tmp_path):
    from harness.candidate_commit import CandidateRefusal, accept

    h = make_harness(tmp_path)
    candidate_id = "sha256:" + "3" * 64
    foreign_id = "sha256:" + "4" * 64
    prepared = h / "evidence" / "candidate-prepared"
    prepared.mkdir()
    (prepared / f"{candidate_id[7:]}.json").write_text(
        json.dumps(
            {
                "schema": "candidate-prepared/v1",
                "domain": "harness:candidate-prepared:v1",
                "candidate_id": candidate_id,
                "candidate_tree": "b" * 40,
                "parent": "a" * 40,
                "selected": [{"path": "src/a.py"}],
            }
        )
    )
    proofs = h / "evidence" / "candidate-proof"
    proofs.mkdir()
    for bound_candidate in (candidate_id, foreign_id):
        proof = {
            "schema": "candidate-proof/v1",
            "domain": "harness:candidate-proof:v1",
            "candidate_id": bound_candidate,
            "execution": {"exit_code": 0},
        }
        encoded = json.dumps(
            proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        proof_id = "sha256:" + hashlib.sha256(
            b"harness:candidate-proof:v1\0" + encoded
        ).hexdigest()
        proof["proof_id"] = proof_id
        (proofs / f"{proof_id[7:]}.json").write_text(
            json.dumps(proof)
        )

    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["status"] = "pending"
    requirements["requirements"][0]["evidence"] = []
    requirements["requirements"][0]["test_plan"]["cases"][0]["tests"] = [
        "tests/test_missing_candidate_coverage.py"
    ]
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    (h / "evidence" / "complexity-review.json").unlink()

    with pytest.raises(CandidateRefusal, match="CANDIDATE_SCHEMA_UNSUPPORTED"):
        accept(tmp_path, candidate_id)
    assert not (h / "evidence" / "candidate-acceptance").exists()

    acceptance_dir = h / "evidence" / "candidate-acceptance"
    assert not acceptance_dir.exists() or not list(acceptance_dir.iterdir())


def _write_candidate_gate_fixture(root: Path):
    from harness.candidate_assessment import POLICY, semantic_source_snapshot

    h = make_harness(root)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    gate_path = h / "gate.yaml"
    gate = yaml.safe_load(gate_path.read_text())
    gate["gate"]["candidate_commit"] = POLICY
    gate_path.write_text(yaml.safe_dump(gate))
    task_path.write_text(yaml.safe_dump(task))
    contracts = h / "interface-contracts"
    contracts.mkdir()
    (contracts / "INT-001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "INT-001",
                "task_id": "TASK-001",
                "status": "DECLARED",
                "name": "candidate adapter fixture",
                "kind": "cli",
                "visibility": "external",
                "consumers": ["tests"],
                "inputs": {"description": "input"},
                "outputs": {"description": "output"},
                "errors": {"description": "errors"},
                "compatibility": {
                    "classification": "compatible",
                    "rationale": "fixture",
                    "migration": None,
                },
                "versioning": {"required": False, "strategy": None},
                "observability": {"contract": "observability.yaml"},
                "decision_refs": [],
                "verification": [],
                "breaking_change_approved": False,
                "breaking_change_reason": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "approved_at": None,
            }
        )
    )
    candidate = {
        "schema": "candidate-prepared/v1",
        "domain": "harness:candidate-prepared:v1",
        "full_ref": "refs/heads/main",
        "index": {},
        "inputs": {},
        "parent": "a" * 40,
        "candidate_tree": "b" * 40,
        "selected": [{"path": "src/a.py"}],
        "semantic_sources": semantic_source_snapshot(h),
    }
    candidate_id = 'sha256:' + hashlib.sha256(b'harness:candidate-prepared:v1\0' + json.dumps(
        candidate, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    candidate['candidate_id'] = candidate_id
    prepared = h / "evidence" / "candidate-prepared"
    prepared.mkdir()
    (prepared / f"{candidate_id[7:]}.json").write_text(json.dumps(candidate))
    proofs = h / "evidence" / "candidate-proof"
    proofs.mkdir()
    source_fingerprint = "sha256:" + "6" * 64
    proof = {
        "schema": "candidate-proof/v1",
        "domain": "harness:candidate-proof:v1",
        "candidate_id": candidate_id,
        "spec_sha256": "sha256:" + "7" * 64,
        "execution": {
            "profile": "python-module-build-v1",
            "argv": [sys.executable, "-S", "build-driver.py"],
            "exit_code": 0,
            "candidate_tree": "b" * 40,
            "parent_commit": "a" * 40,
            "source_before": source_fingerprint,
            "source_after": source_fingerprint,
            "runtime": {
                "implementation": "CPython",
                "version": "3.11.0",
                "executable": sys.executable,
                "resolved_executable": str(Path(sys.executable).resolve()),
                "executable_sha256": "sha256:" + "8" * 64,
            },
            "dependencies": {"files": []},
            "source_config": {
                "schema": "candidate-proof-spec/v1",
                "profile": "python-module-build-v1",
                "environment": {
                    "names": [],
                    "declared": {},
                    "ambient_inherited": [],
                },
                "input_policy": {
                    "git": "forbidden",
                    "hooks": "forbidden",
                    "network": "forbidden",
                    "secrets": "forbidden",
                    "dynamic_dependencies": "forbidden",
                },
                "writable_paths": [".candidate-output"],
            },
            "stdout_sha256": "sha256:" + "9" * 64,
            "stderr_sha256": "sha256:" + "0" * 64,
            "outputs": [],
        },
        "record": {
            "type": "build",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "command": "candidate python-module-build-v1",
            "exit_code": 0,
            "execution_domain": "outside-git",
            "candidate_tree": "b" * 40,
            "source_fingerprint": source_fingerprint,
            "covered_tests": [],
            "covered_test_cases": [],
            "executed_tests": [],
        },
        "qualification": {
            "coverage_complete": True,
            "profile_version": "candidate-proof-profile/v1",
            "evidence_type": "build",
            "bindings": [],
            "interfaces": [],
            "plan_items": [],
        },
    }
    projection = json.dumps(
        proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    proof["proof_id"] = "sha256:" + hashlib.sha256(
        b"harness:candidate-proof:v1\0" + projection
    ).hexdigest()
    proof_path = proofs / f"{proof['proof_id'][7:]}.json"
    proof_path.write_text(json.dumps(proof))
    proof_ref = proof_path.relative_to(root).as_posix()

    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["evidence"] = [proof_ref]
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    invariants = yaml.safe_load((h / "invariants.yaml").read_text())
    invariants["invariants"][0]["verification"] = [proof_ref]
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))

    reviews = h / "evidence" / "candidate-review"
    reviews.mkdir()
    for kind in ("complexity", "diagnosability", "interface"):
        if kind == "complexity":
            record = json.loads((h / "evidence" / "complexity-review.json").read_text())
            source_report = {
                "task": "TASK-001",
                "findings": [],
                "checks": record["checks"],
            }
        elif kind == "diagnosability":
            checks = {
                name: "not_applicable"
                for name in (
                    "business_keys",
                    "external_failure_context",
                    "state_transitions",
                    "caller_rejections",
                    "sensitive_data",
                    "duplicate_exception_logging",
                    "low_value_logging",
                )
            }
            record = {
                "type": "diagnosability_review",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "command": "harness review diagnosability",
                "exit_code": 0,
                "contract_required": False,
                "checks": checks,
                "finding_ids": [],
                "review_scope": {
                    "files": [],
                    "contract_refs": [],
                    "direct_dependencies": [],
                },
            }
            source_report = {
                "task": "TASK-001",
                "contract_required": False,
                "checks": checks,
                "finding_ids": [],
                "direct_dependencies": [],
                "review_scope": {"files": [], "contract_refs": []},
            }
        else:
            checks = {
                name: "not_applicable"
                for name in (
                    "boundary",
                    "dto",
                    "errors",
                    "dependency",
                    "compatibility",
                    "tests",
                )
            }
            record = {
                "type": "review",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "command": "harness review interface",
                "exit_code": 0,
                "contracts": ["INT-001"],
                "checks": checks,
                "proposals": [],
                "finding_mapping": {},
                "review_scope": {"files": [], "contract_refs": ["INT-001"]},
            }
            source_report = {
                "task": "TASK-001",
                "contracts": ["INT-001"],
                "checks": checks,
                "proposals": [],
            }
        for forbidden in (
            "commit",
            "workspace_fingerprint",
            "workspace_fingerprint_after",
        ):
            record.pop(forbidden, None)
        record.update(
            {
                "command": f"harness review {kind}",
                "execution_domain": "outside-git",
                "candidate_tree": "b" * 40,
                "source_fingerprint": source_fingerprint,
            }
        )
        record.setdefault("review_scope", {"files": [], "contract_refs": []})
        record["review_scope"].setdefault("contract_refs", [])
        review = {
            "schema": "candidate-review/v1",
            "domain": "harness:candidate-review:v1",
            "candidate_id": candidate_id,
            "kind": kind,
            "inputs": {
                "manifest": "sha256:" + "1" * 64,
                "scope": "sha256:" + "2" * 64,
                "report": "sha256:" + "3" * 64,
            },
            "report": source_report,
            "record": record,
            "qualification": {
                "candidate_tree": "b" * 40,
                "parent_commit": "a" * 40,
                "source_fingerprint": source_fingerprint,
                "outcome": "PASS",
                "scope_complete": True,
                "review_scope": ["src/a.py"],
            },
        }
        projection = json.dumps(review, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        review["review_id"] = "sha256:" + hashlib.sha256(b"harness:candidate-review:v1\0" + projection).hexdigest()
        (reviews / f"{review['review_id'][7:]}.json").write_text(json.dumps(review))
    candidate["semantic_sources"] = semantic_source_snapshot(h)
    (prepared / f"{candidate_id[7:]}.json").write_text(json.dumps(candidate))
    return h, candidate_id


def _candidate_assessment_view(root: Path, h: Path, candidate_id: str):
    from harness.candidate_assessment import build_candidate_assessment_view

    candidate_path = h / "evidence" / "candidate-prepared" / f"{candidate_id[7:]}.json"
    candidate = json.loads(candidate_path.read_text())
    proofs = tuple(
        (path, json.loads(path.read_text()))
        for path in sorted((h / "evidence" / "candidate-proof").glob("*.json"))
    )
    reviews = tuple(
        (path, json.loads(path.read_text()))
        for path in sorted((h / "evidence" / "candidate-review").glob("*.json"))
    )
    return build_candidate_assessment_view(root, candidate, proofs, reviews)


def _rewrite_candidate_record(path: Path, identifier: str, domain: bytes, mutate):
    record = json.loads(path.read_text())
    record.pop(identifier)
    mutate(record)
    projection = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    record[identifier] = "sha256:" + hashlib.sha256(domain + projection).hexdigest()
    path.unlink()
    rewritten = path.parent / f"{record[identifier][7:]}.json"
    rewritten.write_text(json.dumps(record))
    return rewritten


def test_candidate_gate_preserves_native_unfinished_and_pending_blockers(tmp_path):
    from harness.candidate_assessment import semantic_source_snapshot
    from harness.plan_reconciliation import plan_fingerprint
    from harness.quality_gate import assess_gate

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))

    plan = {"version": 1, "items": [{"id": "P-001", "intent": "finish"}]}
    (h / "plan.yaml").write_text(yaml.safe_dump(plan))
    (h / "plan-execution.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "plan": {
                    "path": ".harness/plan.yaml",
                    "fingerprint": plan_fingerprint(plan),
                },
                "items": {"P-001": {"status": "IN_PROGRESS"}},
            }
        )
    )
    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["status"] = "pending"
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    invariants = yaml.safe_load((h / "invariants.yaml").read_text())
    invariants["invariants"][0]["status"] = "pending"
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))

    prepared_path = next((h / "evidence" / "candidate-prepared").glob("*.json"))
    prepared = json.loads(prepared_path.read_text())
    prepared["semantic_sources"] = semantic_source_snapshot(h)
    prepared_path.write_text(json.dumps(prepared))
    view = _candidate_assessment_view(tmp_path, h, candidate_id)

    assessment = assess_gate(h, assessment_view=view)

    codes = {blocker.code for blocker in assessment.blockers}
    assert "REQUIREMENT_UNVERIFIED" in codes
    assert "INVARIANT_UNVERIFIED" in codes
    assert "PLAN_ITEM_UNRECONCILED" in codes


def test_candidate_verification_entry_preserves_replayed_in_progress_blocker(tmp_path):
    from harness.candidate_assessment import semantic_source_snapshot
    from harness.plan_reconciliation import (
        assess_plan_verification_entry_documents,
        plan_fingerprint,
    )

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"] = {
        "level": "Q3",
        "profile": "STRICT",
        "dimensions": SAFE_DIMENSIONS,
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
    }
    task["plan_reconciliation"] = {"enabled": True, "mode": "task_and_final"}
    task_path.write_text(yaml.safe_dump(task))
    plan = {"version": 1, "items": [{"id": "P-001", "intent": "finish"}]}
    execution = {
        "version": 2,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "sequence": 1,
        "transitions": [
            {
                "sequence": 1,
                "item": "P-001",
                "from": "PENDING",
                "to": "IN_PROGRESS",
                "action": "BEGIN",
            }
        ],
        "items": {"P-001": {"status": "IN_PROGRESS"}},
    }
    (h / "plan.yaml").write_text(yaml.safe_dump(plan))
    (h / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    prepared_path = next((h / "evidence" / "candidate-prepared").glob("*.json"))
    prepared = json.loads(prepared_path.read_text())
    prepared["semantic_sources"] = semantic_source_snapshot(h)
    prepared_path.write_text(json.dumps(prepared))
    view = _candidate_assessment_view(tmp_path, h, candidate_id)

    blockers = assess_plan_verification_entry_documents(
        h, task, plan, execution, assessment_view=view
    )

    assert [(blocker.code, blocker.source) for blocker in blockers] == [
        ("PLAN_ITEM_UNRECONCILED", "P-001")
    ]


def test_candidate_final_plan_rejects_unbound_build_evidence_despite_complete_status(
    tmp_path,
):
    from harness.candidate_assessment import semantic_source_snapshot
    from harness.plan_reconciliation import plan_fingerprint
    from harness.quality_gate import assess_gate

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    task_path.write_text(yaml.safe_dump(task))
    plan = {
        "version": 1,
        "items": [
            {
                "id": "P-001",
                "intent": "finish",
                "test_case_refs": ["REQ-001/TC-002", "INV-001/TC-101"],
            }
        ],
    }
    proof_path = next(
        path
        for path in (h / "evidence" / "candidate-proof").glob("*.json")
        if json.loads(path.read_text())["record"]["type"] == "build"
    )
    proof_ref = proof_path.relative_to(tmp_path).as_posix()
    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["evidence"] = [proof_ref]
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    invariants = yaml.safe_load((h / "invariants.yaml").read_text())
    invariants["invariants"][0]["verification"] = [proof_ref]
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))
    execution = {
        "version": 1,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan),
        },
        "items": {
            "P-001": {"status": "COMPLETE", "evidence_refs": [proof_ref]}
        },
    }
    (h / "plan.yaml").write_text(yaml.safe_dump(plan))
    (h / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    prepared_path = next((h / "evidence" / "candidate-prepared").glob("*.json"))
    prepared = json.loads(prepared_path.read_text())
    prepared["semantic_sources"] = semantic_source_snapshot(h)
    prepared_path.write_text(json.dumps(prepared))

    assessment = assess_gate(
        h, assessment_view=_candidate_assessment_view(tmp_path, h, candidate_id)
    )

    assert any(
        blocker.code.startswith("PLAN_") for blocker in assessment.blockers
    )


def test_candidate_covered_case_does_not_waive_actual_node_coverage(tmp_path):
    from harness.candidate_assessment import semantic_source_snapshot
    from harness.quality_gate import assess_gate

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    test_path = tmp_path / "tests" / "candidate_case.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_expected():\n    pass\n")
    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["test_plan"] = {
        "strategies": ["unit"],
        "cases": [
            {
                "id": "TC-002",
                "type": "regression",
                "strategy": "unit",
                "description": "candidate node coverage",
                "tests": ["tests/candidate_case.py::test_expected"],
            }
        ],
    }
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    prepared_path = next((h / "evidence" / "candidate-prepared").glob("*.json"))
    prepared = json.loads(prepared_path.read_text())
    prepared["semantic_sources"] = semantic_source_snapshot(h)
    prepared_path.write_text(json.dumps(prepared))

    assessment = assess_gate(
        h, assessment_view=_candidate_assessment_view(tmp_path, h, candidate_id)
    )

    assert any(
        blocker.code == "TEST_EVIDENCE_MISSING"
        and blocker.requirement_id == "REQ-001"
        for blocker in assessment.blockers
    )


def test_candidate_declared_evidence_type_requires_matching_raw_record(tmp_path):
    from harness.quality_gate import assess_gate

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    for path in (h / "evidence" / "candidate-proof").glob("*.json"):
        if json.loads(path.read_text())["record"]["type"] == "unit_test":
            path.unlink()

    assessment = assess_gate(
        h, assessment_view=_candidate_assessment_view(tmp_path, h, candidate_id)
    )

    assert any(
        blocker.source == "unit_test" and blocker.code == "EVIDENCE_HEAD_MISMATCH"
        for blocker in assessment.blockers
    )


def test_candidate_verified_obligation_requires_bound_namespaced_evidence(tmp_path):
    from harness.candidate_assessment import semantic_source_snapshot
    from harness.quality_gate import assess_gate

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["evidence"] = ["build.json"]
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    prepared_path = next((h / "evidence" / "candidate-prepared").glob("*.json"))
    prepared = json.loads(prepared_path.read_text())
    prepared["semantic_sources"] = semantic_source_snapshot(h)
    prepared_path.write_text(json.dumps(prepared))

    assessment = assess_gate(
        h, assessment_view=_candidate_assessment_view(tmp_path, h, candidate_id)
    )

    assert any(
        blocker.code == "EVIDENCE_MISSING"
        and blocker.requirement_id == "REQ-001"
        and blocker.source == "build.json"
        for blocker in assessment.blockers
    )


def test_candidate_review_pass_declaration_does_not_waive_review_policy(tmp_path):
    from harness.candidate_assessment import CandidateAssessmentError

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    review_path = next(
        path
        for path in (h / "evidence" / "candidate-review").glob("*.json")
        if json.loads(path.read_text())["kind"] == "complexity"
    )
    _rewrite_candidate_record(
        review_path,
        "review_id",
        b"harness:candidate-review:v1\0",
        lambda record: record["record"]["checks"].pop("shrink"),
    )

    with pytest.raises(CandidateAssessmentError, match="CANDIDATE_REVIEW_UNQUALIFIED"):
        _candidate_assessment_view(tmp_path, h, candidate_id)


def test_candidate_gate_rejects_hand_seeded_receipts_as_complete_lifecycle(tmp_path):
    from harness.candidate_commit import CandidateRefusal, accept

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    before = (h / 'current-task.yaml').read_bytes()

    # Synthetic view records lack actual Git/index preparation attestations.
    with pytest.raises(CandidateRefusal, match="CANDIDATE_DRIFT"):
        accept(tmp_path, candidate_id)
    assert (h / 'current-task.yaml').read_bytes() == before
    acceptance = h / "evidence" / "candidate-acceptance"
    assert not acceptance.exists() or not list(acceptance.iterdir())


@pytest.mark.parametrize("defect", ["missing_review", "wrong_candidate", "incomplete_coverage", "source_changed"])
def test_candidate_gate_rejects_unqualified_view_inputs(tmp_path, defect):
    from harness.candidate_commit import CandidateRefusal, accept

    h, candidate_id = _write_candidate_gate_fixture(tmp_path)
    if defect == "missing_review":
        next((h / "evidence" / "candidate-review").glob("*.json")).unlink()
    elif defect == "wrong_candidate":
        path = next((h / "evidence" / "candidate-proof").glob("*.json"))
        proof = json.loads(path.read_text())
        proof["candidate_id"] = "sha256:" + "9" * 64
        path.write_text(json.dumps(proof))
    elif defect == "incomplete_coverage":
        path = next((h / "evidence" / "candidate-proof").glob("*.json"))
        proof = json.loads(path.read_text())
        proof["qualification"]["coverage_complete"] = False
        path.write_text(json.dumps(proof))
    else:
        requirements = yaml.safe_load((h / "requirements.yaml").read_text())
        requirements["requirements"][0]["statement"] = "changed business input"
        (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))

    with pytest.raises(CandidateRefusal, match="CANDIDATE_GATE_BLOCKED"):
        accept(tmp_path, candidate_id)


def test_candidate_semantic_snapshot_excludes_only_derived_progress(tmp_path):
    from harness.candidate_assessment import semantic_source_snapshot

    h = make_harness(tmp_path)
    plan = {
        "version": 1,
        "items": [{"id": "P-001", "intent": "exercise semantic projection"}],
    }
    (h / "plan.yaml").write_text(yaml.safe_dump(plan))
    plan_fingerprint = "sha256:" + hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    execution = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": plan_fingerprint},
        "items": {"P-001": {"status": "PENDING"}},
    }
    (h / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    (h / "alignment.yaml").write_text(
        yaml.safe_dump(
            {
                "decision_ids": ["DEC-001"],
                "interface_contract_ids": ["INT-001"],
            }
        )
    )
    decisions = h / "decisions"
    decisions.mkdir(exist_ok=True)
    (decisions / "DEC-001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "DEC-001",
                "task_id": "TASK-001",
                "status": "ACCEPTED",
                "selected": {"option": "bounded"},
            }
        )
    )
    interfaces = h / "interface-contracts"
    interfaces.mkdir(exist_ok=True)
    interface = {
        "id": "INT-001",
        "task_id": "TASK-001",
        "inputs": {"description": "stable input"},
        "verification": [],
    }
    (interfaces / "INT-001.yaml").write_text(yaml.safe_dump(interface))
    original = semantic_source_snapshot(h)

    requirements = yaml.safe_load((h / "requirements.yaml").read_text())
    requirements["requirements"][0]["status"] = "verified"
    requirements["requirements"][0]["evidence"] = ["candidate-proof/example.json"]
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    invariants = yaml.safe_load((h / "invariants.yaml").read_text())
    invariants["invariants"][0]["status"] = "verified"
    invariants["invariants"][0]["verification"] = ["candidate-proof/example.json"]
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))
    execution = yaml.safe_load((h / "plan-execution.yaml").read_text())
    execution["items"]["P-001"] = {"status": "IN_PROGRESS"}
    (h / "plan-execution.yaml").write_text(yaml.safe_dump(execution))
    interface["verification"] = ["candidate-proof/example.json"]
    (interfaces / "INT-001.yaml").write_text(yaml.safe_dump(interface))

    assert semantic_source_snapshot(h) == original

    interface["inputs"]["description"] = "changed interface"
    (interfaces / "INT-001.yaml").write_text(yaml.safe_dump(interface))
    assert semantic_source_snapshot(h) != original
    interface["inputs"]["description"] = "stable input"
    (interfaces / "INT-001.yaml").write_text(yaml.safe_dump(interface))
    requirements["requirements"][0]["statement"] += " changed contract"
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    assert semantic_source_snapshot(h) != original


def _candidate_runner_repository(tmp_path: Path, files: dict[str, str]):
    root = tmp_path / "candidate-repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Candidate Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "candidate@example.invalid"],
        cwd=root,
        check=True,
    )
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return root, {"parent": parent, "candidate_tree": tree}


def _candidate_profile(profile: str, **overrides):
    value = {
        "schema": "candidate-proof-spec/v1",
        "profile": profile,
        "interpreter": sys.executable,
        "dependencies": [],
        "environment": {"SOURCE_DATE_EPOCH": "0"},
        "writable_paths": [".candidate-output"],
        "input_policy": {
            "git": "forbidden",
            "hooks": "forbidden",
            "network": "forbidden",
            "secrets": "forbidden",
            "dynamic_dependencies": "forbidden",
        },
    }
    value.update(overrides)
    return value


def _pytest_dependency_files():
    site_packages = Path(pytest.__file__).resolve().parent.parent
    names = (
        "pytest",
        "_pytest",
        "pluggy",
        "iniconfig",
        "packaging",
        "pygments",
    )
    roots = [site_packages / name for name in names]
    roots.append(site_packages / "py.py")
    for distribution in ("pytest", "pluggy", "iniconfig", "packaging", "pygments", "py"):
        roots.extend(site_packages.glob(f"{distribution.replace('-', '_')}-*.dist-info"))
    declarations = []
    for root in roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if path.is_file() and not path.is_symlink():
                declarations.append(
                    {
                        "source": path.as_posix(),
                        "target": path.relative_to(site_packages).as_posix(),
                    }
                )
    return declarations


def _build_dependency_files():
    frontend = shutil.which("pyproject-build")
    if frontend is None:
        pytest.skip("qualified local build frontend is unavailable")
    environments = sorted((Path(frontend).resolve().parent.parent / "lib").glob(
        "python*/site-packages"
    ))
    if len(environments) != 1:
        pytest.skip("qualified local build frontend is ambiguous")
    site_packages = environments[0]
    roots = [site_packages / name for name in ("build", "pyproject_hooks", "packaging")]
    for distribution in ("build", "pyproject_hooks", "packaging"):
        roots.extend(site_packages.glob(f"{distribution}-*.dist-info"))
    declarations = []
    for root in roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if path.is_file() and not path.is_symlink():
                declarations.append(
                    {
                        "source": path.as_posix(),
                        "target": path.relative_to(site_packages).as_posix(),
                    }
                )
    return declarations


def test_candidate_runtime_binds_stdlib_native_libraries_and_configuration():
    import sysconfig
    from harness.candidate_runner import _runtime

    runtime = _runtime(sys.executable)
    assert 'runtime_inputs' in runtime
    inputs = runtime['runtime_inputs']
    source = Path(sysconfig.get_path('stdlib')) / 'json/__init__.py'
    assert any(item['source'] == str(source.resolve()) and
               item['sha256'] == 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()
               for item in inputs['files'])
    assert inputs['stdlib_roots']
    assert inputs['library_root']
    assert runtime['platform']['system']


def test_runtime_input_manifest_rehashes_bytes_membership_and_missing_configuration(tmp_path):
    from harness.candidate_runner import _runtime_inputs

    stdlib, library = tmp_path / 'stdlib', tmp_path / 'lib'
    stdlib.mkdir()
    library.mkdir()
    source = stdlib / 'module.py'
    source.write_text('value=1\n')
    native = library / 'libfixture.dylib'
    native.write_bytes(b'AAAA')
    config = tmp_path / 'pyvenv.cfg'
    original_stat = native.stat()
    first = _runtime_inputs([str(stdlib)], str(library), [str(config)])
    native.write_bytes(b'BBBB')
    os.utime(native, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second = _runtime_inputs([str(stdlib)], str(library), [str(config)])
    assert first != second  # identical size/inode/mtime must not reuse a digest
    (library / 'new.dylib').write_bytes(b'new')
    third = _runtime_inputs([str(stdlib)], str(library), [str(config)])
    assert len(third['files']) == len(second['files']) + 1
    config.write_text('home = qualified-runtime\n')
    fourth = _runtime_inputs([str(stdlib)], str(library), [str(config)])
    assert third['configuration'][str(config)] is None
    assert fourth['configuration'][str(config)] == 'sha256:' + hashlib.sha256(config.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind', ['fifo', 'escaping_link', 'directory_link'])
def test_runtime_input_manifest_refuses_special_or_escaping_sources(tmp_path, kind):
    from harness.candidate_runner import CandidateRunnerError, _runtime_inputs
    stdlib, library = tmp_path / 'stdlib', tmp_path / 'lib'
    stdlib.mkdir()
    library.mkdir()
    if kind == 'fifo':
        os.mkfifo(stdlib / 'unsafe.py')
    elif kind == 'escaping_link':
        target = tmp_path / 'outside.py'
        target.write_text('secret = 1')
        (stdlib / 'unsafe.py').symlink_to(target)
    else:
        (stdlib / 'alias').symlink_to(library, target_is_directory=True)
    with pytest.raises(CandidateRunnerError, match='CANDIDATE_PROOF_UNQUALIFIED'):
        _runtime_inputs([str(stdlib)], str(library), [])


def test_native_runtime_resolves_inherited_rpath_at_executable_not_importing_image(tmp_path, monkeypatch):
    from harness import candidate_runner as runner
    library = tmp_path / 'lib'
    stdlib = library / 'python3.11'
    extension = stdlib / 'lib-dynload/module.so'
    extension.parent.mkdir(parents=True)
    extension.write_bytes(b'extension')
    dependency = library / 'libleaf.dylib'
    dependency.write_bytes(b'native')
    executable = tmp_path / 'bin/python'
    executable.parent.mkdir()
    executable.write_bytes(b'executable')
    inputs = runner._runtime_inputs([str(stdlib)], str(library), [])
    def commands(name, fingerprint, tool_fingerprint):
        if name == str(executable):
            return (), ('@loader_path/../lib',)
        if name == str(extension):
            return ('@rpath/libleaf.dylib',), ()
        return (), ()
    monkeypatch.setattr(runner, '_native_load_commands', commands)
    runner._verify_native_runtime(executable, inputs)


def test_candidate_proof_refuses_runtime_replacement_after_successful_process(tmp_path, monkeypatch):
    from harness import candidate_runner as runner

    runtime = tmp_path / 'qualified-runtime'
    (runtime / 'bin').mkdir(parents=True)
    interpreter = runtime / 'bin/python'
    shutil.copy2(Path(sys.executable).resolve(), interpreter)
    original_lib = Path(sys.executable).resolve().parent.parent / 'lib'
    (runtime / 'lib').symlink_to(original_lib, target_is_directory=True)
    runner._runtime(str(interpreter))  # actual CPython; not a mocked runtime identity
    root, candidate = _candidate_runner_repository(tmp_path, {'probe.py': "print('real process completed')\n"})
    spec = _candidate_profile('python-script-v1', interpreter=str(interpreter), script='probe.py', args=[])
    original = runner.subprocess.run
    replaced = []
    def external_replacement(*args, **kwargs):
        result = original(*args, **kwargs)
        command = args[0]
        if command[:3] == [str(interpreter), '-S', 'probe.py']:
            assert result.returncode == 0
            interpreter.unlink()
            shutil.copyfile('/usr/bin/true', interpreter)
            interpreter.chmod(0o755)
            replaced.append(True)
        return result
    monkeypatch.setattr(runner.subprocess, 'run', external_replacement)
    with pytest.raises(runner.CandidateRunnerError):
        runner.run(root, candidate, spec)
    assert replaced == [True]


def test_candidate_runtime_refuses_an_unbound_interpreter_delegate(tmp_path):
    from harness.candidate_runner import CandidateRunnerError, _runtime
    import shlex

    wrapper = tmp_path / 'python'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
    wrapper.chmod(0o755)
    with pytest.raises(CandidateRunnerError, match='CANDIDATE_PROOF_UNQUALIFIED'):
        _runtime(str(wrapper))


def test_candidate_script_profile_runs_real_outside_git_with_bound_inputs(tmp_path):
    from harness.candidate_runner import run

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {
            "probe.py": """
import os
from pathlib import Path

root = Path.cwd()
assert not any((parent / '.git').exists() for parent in (root, *root.parents))
assert os.environ['SOURCE_DATE_EPOCH'] == '0'
assert 'UNBOUND_CANDIDATE_SECRET' not in os.environ
target = root / '.candidate-output' / 'result.txt'
target.write_text('real execution\\n')
""",
        },
    )

    result = run(
        root,
        candidate,
        _candidate_profile(
            "python-script-v1", script="probe.py", args=[]
        ),
    )

    execution = result["execution"]
    assert execution["exit_code"] == 0
    assert execution["source_before"] == execution["source_after"]
    assert execution["runtime"]["executable_sha256"].startswith("sha256:")
    assert execution["dependencies"] == {"files": []}
    assert execution["outputs"] == [
        {
            "path": ".candidate-output/result.txt",
            "sha256": "sha256:7d8f0ce63d10e79cb027c32d7654d5651fd659d5cfadb0b068ff4b83b67e7c6f",
            "size": 15,
        }
    ]
    assert result["record"]["execution_domain"] == "outside-git"
    assert "commit" not in result["record"]
    assert "workspace_fingerprint" not in result["record"]


def test_candidate_script_profile_accepts_only_in_export_relative_links(tmp_path):
    from harness.candidate_runner import run

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {
            "probe.py": """
from pathlib import Path

assert Path('assets/alias.txt').read_text() == 'bound input\\n'
Path('.candidate-output/result.txt').write_text('ok\\n')
""",
            "data.txt": "bound input\n",
        },
    )
    (root / "assets").mkdir()
    (root / "assets" / "alias.txt").symlink_to("../data.txt")
    subprocess.run(["git", "add", "assets/alias.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--amend", "-qm", "fixture with link"], cwd=root, check=True)
    candidate["parent"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    candidate["candidate_tree"] = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()

    result = run(
        root,
        candidate,
        _candidate_profile("python-script-v1", script="probe.py", args=[]),
    )

    assert result["execution"]["exit_code"] == 0
    assert result["execution"]["source_before"] == result["execution"]["source_after"]


@pytest.mark.parametrize("defect", ["escape", "dangling", "gitlink"])
def test_candidate_runner_rejects_unsafe_export_nodes(tmp_path, defect):
    from harness.candidate_runner import CandidateRunnerError, run

    root, candidate = _candidate_runner_repository(
        tmp_path, {"probe.py": "print('must not execute')\n"}
    )
    if defect in {"escape", "dangling"}:
        (root / "unsafe-link").symlink_to(
            "../outside-export" if defect == "escape" else "missing-target"
        )
        subprocess.run(["git", "add", "unsafe-link"], cwd=root, check=True)
    else:
        subprocess.run(
            [
                "git",
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{candidate['parent']},unsafe-gitlink",
            ],
            cwd=root,
            check=True,
        )
    subprocess.run(["git", "commit", "--amend", "-qm", "unsafe tree"], cwd=root, check=True)
    candidate["parent"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    candidate["candidate_tree"] = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()

    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            _candidate_profile("python-script-v1", script="probe.py", args=[]),
        )


def test_candidate_pytest_profile_uses_actual_parameterized_junit_bindings(tmp_path):
    from harness.candidate_assessment import semantic_source_snapshot
    from harness.candidate_runner import run

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {
            "tests/test_sample.py": """
import pytest

@pytest.mark.parametrize('value', [1, 2], ids=['one', 'two'])
def test_bound(value):
    assert value in {1, 2}
""",
        },
    )
    harness = root / ".harness"
    harness.mkdir()
    (harness / "current-task.yaml").write_text(
        yaml.safe_dump({"task": {"id": "TASK-001", "type": "feature"}})
    )
    requirements = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "parameterized execution is observed",
                "priority": "must",
                "status": "pending",
                "evidence": [],
                "test_plan": {
                    "strategies": ["unit"],
                    "cases": [
                        {
                            "id": "TC-001",
                            "type": "happy_path",
                            "strategy": "unit",
                            "description": "run every parameter",
                            "tests": ["tests/test_sample.py::test_bound"],
                        }
                    ],
                },
            }
        ]
    }
    (harness / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    (harness / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))
    (harness / "plan.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "items": [
                    {
                        "id": "P-001",
                        "intent": "prove parameterized behavior",
                        "requirement_refs": ["REQ-001"],
                        "test_case_refs": ["REQ-001/TC-001"],
                    }
                ],
            }
        )
    )
    contracts = harness / "interface-contracts"
    contracts.mkdir()
    (contracts / "INT-001.yaml").write_text(
        yaml.safe_dump({"id": "INT-001", "verification": []})
    )
    for name, value in (
        ("alignment.yaml", {"interface_contract_ids": ["INT-001"]}),
        ("impact.yaml", {}),
        ("gate.yaml", {}),
    ):
        (harness / name).write_text(yaml.safe_dump(value))
    subprocess.run(["git", "add", ".harness"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--amend", "-qm", "fixture with contracts"], cwd=root, check=True)
    candidate["parent"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    candidate["candidate_tree"] = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    candidate["semantic_sources"] = semantic_source_snapshot(harness)

    result = run(
        root,
        candidate,
        _candidate_profile(
            "pytest-junit-v1",
            dependencies=_pytest_dependency_files(),
            selectors=["tests/test_sample.py::test_bound"],
            evidence_type="unit_test",
        ),
    )

    assert result["record"]["executed_tests"] == [
        "tests/test_sample.py::test_bound[one]",
        "tests/test_sample.py::test_bound[two]",
    ]
    assert result["record"]["covered_tests"] == [
        "tests/test_sample.py::test_bound"
    ]
    assert result["qualification"]["bindings"] == [
        {
            "case_ref": "REQ-001/TC-001",
            "obligation_ref": "REQ-001",
            "tests": ["tests/test_sample.py::test_bound"],
            "executed_nodes": [
                "tests/test_sample.py::test_bound[one]",
                "tests/test_sample.py::test_bound[two]",
            ],
        }
    ]
    assert result["qualification"]["plan_items"] == ["P-001"]
    assert result["qualification"]["interfaces"] == ["INT-001"]
    assert all("junit.xml" not in node for node in result["record"]["executed_tests"])


def test_candidate_build_profile_runs_real_local_backend_without_network(tmp_path):
    from harness.candidate_runner import run

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {
            "pyproject.toml": """
[build-system]
requires = []
build-backend = "backend"
backend-path = ["."]
""",
            "backend.py": """
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    target = Path(wheel_directory) / 'fixture-1.0-py3-none-any.whl'
    entries = {
        'fixture-1.0.dist-info/METADATA': b'Metadata-Version: 2.1\\nName: fixture\\nVersion: 1.0\\n',
        'fixture-1.0.dist-info/WHEEL': b'Wheel-Version: 1.0\\nGenerator: candidate-test\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n',
    }
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            archive.writestr(info, data)
    return target.name
""",
        },
    )

    result = run(
        root,
        candidate,
        _candidate_profile(
            "python-module-build-v1", dependencies=_build_dependency_files()
        ),
    )

    assert result["record"]["type"] == "build"
    assert result["execution"]["argv"][1:5] == [
        "-S",
        "-m",
        "build",
        "--no-isolation",
    ]
    assert result["record"]["executed_tests"] == []
    wheels = [
        item
        for item in result["execution"]["outputs"]
        if item["path"].endswith("fixture-1.0-py3-none-any.whl")
    ]
    assert len(wheels) == 1 and wheels[0]["sha256"].startswith("sha256:")
    assert result["execution"]["source_before"] == result["execution"]["source_after"]


def _bind_runner_preparation(harness, candidate):
    from harness.candidate_assessment import semantic_source_snapshot

    candidate.update(full_ref=subprocess.check_output(
        ['git', 'symbolic-ref', 'HEAD'], cwd=harness.parent, text=True).strip(),
        index={}, inputs={}, semantic_sources=semantic_source_snapshot(harness))
    candidate.pop('candidate_id', None)
    identifier = 'sha256:' + hashlib.sha256(b'harness:candidate-prepared:v1\0' + json.dumps(
        candidate, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    candidate['candidate_id'] = identifier
    return identifier


def test_candidate_prove_writes_honest_schema_valid_candidate_record(tmp_path):
    from jsonschema import validate

    from harness.candidate_commit import prove
    from harness.schema_resources import read_schema

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {"probe.py": "print('qualified real process')\n"},
    )
    candidate_id = "sha256:" + "3" * 64
    candidate.update(
        {
            "schema": "candidate-prepared/v1",
            "domain": "harness:candidate-prepared:v1",
            "candidate_id": candidate_id,
            "selected": [{"path": "probe.py"}],
        }
    )
    harness = root / ".harness"
    prepared = harness / "evidence" / "candidate-prepared"
    prepared.mkdir(parents=True)
    (harness / "current-task.yaml").write_text(
        yaml.safe_dump({"state": "IMPLEMENTING"})
    )
    candidate_id = _bind_runner_preparation(harness, candidate)
    (prepared / f"{candidate_id[7:]}.json").write_text(json.dumps(candidate))
    spec = tmp_path / "proof-spec.json"
    spec.write_text(
        json.dumps(
            _candidate_profile(
                "python-script-v1", script="probe.py", args=[]
            )
        )
    )

    result = prove(root, candidate_id, spec)

    proof = json.loads((root / result["record"]).read_text())
    validate(proof, read_schema("candidate-proof.schema.json"))
    assert proof["record"]["execution_domain"] == "outside-git"
    assert "commit" not in proof["record"]
    assert "workspace_fingerprint" not in proof["record"]
    assert proof["execution"]["exit_code"] == 0
    assert result["status"] == "PROVED"


def test_candidate_review_writer_derives_valid_complexity_record(tmp_path):
    from jsonschema import validate

    from harness.candidate_assessment import (
        build_candidate_assessment_view,
        semantic_source_snapshot,
    )
    from harness.candidate_commit import prove, review_record
    from harness.schema_resources import read_schema

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {"probe.py": "print('reviewed candidate')\n"},
    )
    candidate_id = "sha256:" + "4" * 64
    candidate.update(
        {
            "schema": "candidate-prepared/v1",
            "domain": "harness:candidate-prepared:v1",
            "candidate_id": candidate_id,
            "selected": [{"path": "probe.py"}],
        }
    )
    harness = root / ".harness"
    prepared = harness / "evidence" / "candidate-prepared"
    prepared.mkdir(parents=True)
    task = {
        "state": "IMPLEMENTING",
        "task": {"id": "TASK-001", "type": "feature"},
        "scope": {"owned_paths": ["probe.py"], "protected_user_paths": []},
        "gate": {
            "candidate_commit": {
                "format": "candidate-commit/v1",
                "capability_version": 1,
                "minimum_reader": "0.3.2",
            }
        },
    }
    (harness / "gate.yaml").write_text(yaml.safe_dump({"gate": task.pop("gate")}))
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task))
    (harness / "impact.yaml").write_text(yaml.safe_dump({"impact": {}}))
    (harness / "observability.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "required": False,
                "applicability": {
                    "reasons": ["pure calculation"],
                    "inspected_paths": ["probe.py"],
                },
            }
        )
    )
    contracts = harness / "interface-contracts"
    contracts.mkdir()
    interface_contract = {
        "id": "INT-001",
        "task_id": "TASK-001",
        "status": "DECLARED",
        "name": "fixture interface",
        "kind": "cli",
        "visibility": "external",
        "consumers": ["tests"],
        "inputs": {"description": "input"},
        "outputs": {"description": "output"},
        "errors": {"description": "errors"},
        "compatibility": {
            "classification": "compatible",
            "rationale": "fixture",
            "migration": None,
        },
        "versioning": {"required": False, "strategy": None},
        "observability": {"contract": "observability.yaml"},
        "decision_refs": [],
        "verification": [],
        "breaking_change_approved": False,
        "breaking_change_reason": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "approved_at": None,
    }
    (contracts / "INT-001.yaml").write_text(yaml.safe_dump(interface_contract))
    (harness / "alignment.yaml").write_text(
        yaml.safe_dump({"interface_contract_ids": ["INT-001"]})
    )
    candidate_id = _bind_runner_preparation(harness, candidate)
    manifest = prepared / f"{candidate_id[7:]}.json"
    manifest.write_text(json.dumps(candidate))
    spec = tmp_path / "proof-spec.json"
    spec.write_text(
        json.dumps(
            _candidate_profile("python-script-v1", script="probe.py", args=[])
        )
    )
    proof_result = prove(root, candidate_id, spec)
    proof = json.loads((root / proof_result["record"]).read_text())
    task["state"] = "VERIFYING"
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task))
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "schema": "candidate-review-scope/v1",
                "candidate_id": candidate_id,
                "kind": "complexity",
                "source_fingerprint": proof["execution"]["source_before"],
                "files": ["probe.py"],
                "contract_refs": [],
                "direct_dependencies": [],
            }
        )
    )
    checks = {
        name: {"result": "pass", "evidence": f"{name} checked"}
        for name in ("delete", "reuse", "stdlib", "native", "yagni", "shrink")
    }
    report = tmp_path / "complexity-report.json"
    report.write_text(
        json.dumps({"task": "TASK-001", "findings": [], "checks": checks})
    )

    result = review_record(
        root, candidate_id, "complexity", manifest, scope, report
    )

    review = json.loads((root / result["record"]).read_text())
    validate(review, read_schema("candidate-review.schema.json"))
    assert review["qualification"]["outcome"] == "PASS"
    assert review["qualification"]["review_scope"] == ["probe.py"]
    assert review["record"]["execution_domain"] == "outside-git"
    assert "commit" not in review["record"]
    assert review["inputs"]["report"] == "sha256:" + hashlib.sha256(
        report.read_bytes()
    ).hexdigest()

    from harness.candidate_commit import CandidateRefusal

    bad_scope = tmp_path / "bad-scope.json"
    bad_scope.write_text(scope.read_text().replace(candidate_id, "sha256:" + "9" * 64))
    with pytest.raises(CandidateRefusal, match="CANDIDATE_REVIEW_UNQUALIFIED"):
        review_record(root, candidate_id, "complexity", manifest, bad_scope, report)
    bad_report = tmp_path / "bad-complexity-report.json"
    bad_report.write_text(
        json.dumps(
            {
                "task": "TASK-001",
                "checks": {**checks, "delete": {"result": "fail", "evidence": "failed"}},
                "findings": [
                    {
                        "id": "CPLX-001",
                        "category": "complexity",
                        "type": "delete",
                        "severity": "critical",
                        "status": "open",
                        "location": {"file": "probe.py"},
                        "summary": "invalid severity",
                        "reason": "invalid",
                        "evidence": {"line": 1},
                        "recommendation": "fix",
                    }
                ],
            }
        )
    )
    with pytest.raises(CandidateRefusal, match="CANDIDATE_REVIEW_UNQUALIFIED"):
        review_record(root, candidate_id, "complexity", manifest, scope, bad_report)

    (harness / "observability.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "required": False,
                "applicability": {
                    "reasons": ["pure calculation"],
                    "inspected_paths": ["probe.py"],
                },
            }
        )
    )
    diagnostic_scope = tmp_path / "diagnostic-scope.json"
    diagnostic_scope.write_text(
        json.dumps(
            {
                "schema": "candidate-review-scope/v1",
                "candidate_id": candidate_id,
                "kind": "diagnosability",
                "source_fingerprint": proof["execution"]["source_before"],
                "files": ["probe.py"],
                "contract_refs": [],
                "direct_dependencies": [],
            }
        )
    )
    diagnostic_report = tmp_path / "diagnostic-report.json"
    diagnostic_report.write_text(
        json.dumps(
            {
                "task": "TASK-001",
                "contract_required": False,
                "finding_ids": [],
                "direct_dependencies": [],
                "review_scope": {"files": ["probe.py"], "contract_refs": []},
                "checks": {
                    name: "not_applicable"
                    for name in (
                        "business_keys",
                        "external_failure_context",
                        "state_transitions",
                        "caller_rejections",
                        "sensitive_data",
                        "duplicate_exception_logging",
                        "low_value_logging",
                    )
                },
            }
        )
    )
    diagnostic_result = review_record(
        root,
        candidate_id,
        "diagnosability",
        manifest,
        diagnostic_scope,
        diagnostic_report,
    )
    diagnostic_review = json.loads((root / diagnostic_result["record"]).read_text())
    validate(diagnostic_review, read_schema("candidate-review.schema.json"))
    assert diagnostic_review["record"]["type"] == "diagnosability_review"

    contracts = harness / "interface-contracts"
    (contracts / "INT-001.yaml").write_text(
        yaml.safe_dump(
            interface_contract
        )
    )
    interface_scope = tmp_path / "interface-scope.json"
    interface_scope.write_text(
        json.dumps(
            {
                "schema": "candidate-review-scope/v1",
                "candidate_id": candidate_id,
                "kind": "interface",
                "source_fingerprint": proof["execution"]["source_before"],
                "files": ["probe.py"],
                "contract_refs": [],
                "direct_dependencies": [],
            }
        )
    )
    interface_report = tmp_path / "interface-report.json"
    interface_report.write_text(
        json.dumps(
            {
                "task": "TASK-001",
                "contracts": ["INT-001"],
                "checks": {
                    name: "pass"
                    for name in (
                        "boundary",
                        "dto",
                        "errors",
                        "dependency",
                        "compatibility",
                        "tests",
                    )
                },
                "proposals": [],
            }
        )
    )
    interface_result = review_record(
        root,
        candidate_id,
        "interface",
        manifest,
        interface_scope,
        interface_report,
    )
    interface_review = json.loads((root / interface_result["record"]).read_text())
    validate(interface_review, read_schema("candidate-review.schema.json"))
    assert interface_review["record"]["contracts"] == ["INT-001"]

    view = build_candidate_assessment_view(
        root,
        candidate,
        tuple(
            (path, json.loads(path.read_text()))
            for path in (harness / "evidence" / "candidate-proof").glob("*.json")
        ),
        tuple(
            (path, json.loads(path.read_text()))
            for path in (harness / "evidence" / "candidate-review").glob("*.json")
        ),
    )
    assert view.review_record("complexity")["commit"] == candidate["candidate_tree"]
    assert "commit" not in review["record"]


def test_native_requirement_verification_consumes_candidate_domain_without_reviews(tmp_path, monkeypatch):
    from harness import controlplane
    from harness.candidate_commit import prepare, prove
    from harness.candidate_assessment import POLICY

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / 'config'))
    root, _ = _candidate_pytest_contract_repository(tmp_path, 'def test_bound():\n    assert 2 + 2 == 4\n')
    subprocess.run(['git', 'rm', '-r', '--cached', '.harness'], cwd=root, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '--amend', '-qm', 'untracked control metadata'], cwd=root, check=True)
    harness = root / '.harness'
    task = yaml.safe_load((harness / 'current-task.yaml').read_text())
    task['task']['title'] = 'candidate native verification'
    task.update({'state': 'IMPLEMENTING', 'scope': {'owned_paths': ['tests/test_sample.py'], 'protected_user_paths': []},
                 'risk': {'level': 'Q3', 'profile': 'STRICT', 'dimensions': {
                     key: 'high' for key in ('scope', 'contract', 'data', 'authorization', 'security', 'concurrency', 'deployment')},
                     'escalation_history': [], 'user_changes': {'paths': [], 'fingerprint': ''}},
                 'plan_reconciliation': {'enabled': True, 'mode': 'task_and_final'}})
    (harness / 'current-task.yaml').write_text(yaml.safe_dump(task))
    (harness / 'gate.yaml').write_text(yaml.safe_dump({'gate': {'candidate_commit': POLICY}}))
    case = {'id': 'TC-001', 'type': 'invariant', 'strategy': 'unit',
            'description': 'actual bound node', 'tests': ['tests/test_sample.py::test_bound']}
    invariant = {'id': 'INV-001', 'statement': 'bound assertion holds', 'category': 'correctness',
                 'severity': 'critical', 'status': 'pending', 'verification': [],
                 'test_plan': {'strategies': ['unit'], 'cases': [case]}}
    (harness / 'invariants.yaml').write_text(yaml.safe_dump({'invariants': [invariant]}))
    from harness.interface_contract import declare
    contract = declare(harness, {'name': 'bound calculation', 'kind': 'cli', 'visibility': 'external',
        'consumers': ['fixture'], 'inputs': {'description': 'two values'}, 'outputs': {'description': 'sum'},
        'errors': {'description': 'typed failures'}, 'compatibility': {'classification': 'compatible',
        'rationale': 'fixture', 'migration': None}, 'versioning': {'required': False, 'strategy': None},
        'observability': {'contract': 'observability.yaml'}, 'decision_refs': [], 'verification': []})
    (harness / 'alignment.yaml').write_text(yaml.safe_dump({'interface_contract_ids': [contract['id']]}))
    from harness.plan_execution import semantic_plan_fingerprint
    from types import SimpleNamespace
    plan = yaml.safe_load((harness / 'plan.yaml').read_text())
    execution = {'version': 2, 'plan': {'path': '.harness/plan.yaml', 'fingerprint': semantic_plan_fingerprint(plan)},
                 'items': {}, 'sequence': 0, 'transitions': []}
    (harness / 'plan-execution.yaml').write_text(yaml.safe_dump(execution))
    with monkeypatch.context() as local:
        local.chdir(root)
        assert controlplane.cmd_plan_mutation(SimpleNamespace(plan_command='begin', item_id='P-001')) == 0
    prepared = prepare(root, ['tests/test_sample.py'])
    spec = tmp_path / 'proof-spec.json'
    spec.write_text(json.dumps(_candidate_profile('pytest-junit-v1',
        selectors=['tests/test_sample.py::test_bound'], evidence_type='unit_test',
        dependencies=_pytest_dependency_files())))
    proof = prove(root, prepared['candidate'], spec)
    raw = (root / proof['record']).read_bytes()
    monkeypatch.chdir(root)
    assert controlplane.cmd_requirement_verify('REQ-001', proof['record']) == 0
    requirement = yaml.safe_load((harness / 'requirements.yaml').read_text())['requirements'][0]
    assert requirement['status'] == 'verified'
    assert requirement['evidence'] == [proof['record']]
    assert controlplane.cmd_invariant_verify('INV-001', proof['record']) == 0
    verified = yaml.safe_load((harness / 'invariants.yaml').read_text())['invariants'][0]
    assert verified['status'] == 'verified'
    assert verified['verification'] == [proof['record']]
    from types import SimpleNamespace
    args = SimpleNamespace(interface_command='verify', id=contract['id'], evidence=proof['record'])
    assert controlplane.cmd_interface(args) == 0
    verified_contract = yaml.safe_load((harness / 'interface-contracts' / (contract['id'] + '.yaml')).read_text())
    assert verified_contract['verification'] == [proof['record']]
    args = SimpleNamespace(plan_command='reconcile', item_id='P-001', plan_disposition='COMPLETE',
                           evidence=[proof['record']], surface=[])
    assert controlplane.cmd_plan_mutation(args) == 0
    execution = yaml.safe_load((harness / 'plan-execution.yaml').read_text())
    assert execution['items']['P-001']['status'] == 'COMPLETE'
    receipt = execution['transitions'][-1]['proof_receipt']
    assert receipt['execution_domain'] == 'harness:candidate-assessment:v1'
    assert receipt['candidate_id'] == prepared['candidate']
    assert receipt['evidence'][0]['ref'] == proof['record']
    assert 'commit' not in receipt['evidence'][0]
    from harness.candidate_assessment import active_assessment_view
    from harness.plan_reconciliation import assess_plan_reconciliation_documents
    view = active_assessment_view(harness, require_reviews=False)
    assessment = assess_plan_reconciliation_documents(harness, task, plan, execution,
        head=view.candidate_tree, workspace=view.export_fingerprint, assessment_view=view)
    assert not assessment.blockers
    assert (root / proof['record']).read_bytes() == raw
    assert yaml.safe_load((harness / 'current-task.yaml').read_text())['state'] == 'IMPLEMENTING'


def test_candidate_dependency_swap_to_fifo_refuses_without_blocking(tmp_path):
    import os
    import sys

    target = tmp_path / "dependency.py"
    target.write_text("VALUE = 1\n")
    script = '''
import os, sys
from pathlib import Path
from harness.candidate_runner import CandidateRunnerError, _regular_bytes
path = Path(sys.argv[1])
original = os.open
swapped = [False]
def raced_open(name, flags, *args, **kwargs):
    if os.fspath(name) == str(path) and not swapped[0]:
        swapped[0] = True
        path.unlink()
        os.mkfifo(path)
    return original(name, flags, *args, **kwargs)
os.open = raced_open
try:
    _regular_bytes(path)
except CandidateRunnerError:
    print('REFUSED')
else:
    raise AssertionError('special node accepted')
'''
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    try:
        child = subprocess.run([sys.executable, "-c", script, str(target)], env=env,
                               capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        pytest.fail("candidate dependency reader blocked on replaced FIFO")
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "REFUSED"


def test_candidate_runner_rejects_unbound_mutable_and_unsafe_inputs(tmp_path):
    from harness.candidate_runner import CandidateRunnerError, run

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {
            "probe.py": """
from pathlib import Path
Path('probe.py').chmod(0o644)
Path('probe.py').write_text('mutated')
""",
        },
    )
    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            {
                **_candidate_profile(
                    "python-script-v1", script="probe.py", args=[]
                ),
                "head": candidate["parent"],
            },
        )
    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            _candidate_profile(
                "python-script-v1",
                script="probe.py",
                args=[],
                writable_paths=["probe.py"],
            ),
        )
    with pytest.raises(CandidateRunnerError, match="CANDIDATE_DRIFT"):
        run(
            root,
            candidate,
            _candidate_profile("python-script-v1", script="probe.py", args=[]),
        )

    fifo = tmp_path / "dependency.fifo"
    os.mkfifo(fifo)
    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            _candidate_profile(
                "python-script-v1",
                script="probe.py",
                args=[],
                dependencies=[{"source": str(fifo), "target": "unsafe.py"}],
            ),
        )
    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            _candidate_profile(
                "python-script-v1",
                script="probe.py",
                args=[],
                environment={"UNDECLARED_INPUT": "secret"},
            ),
        )
    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            _candidate_profile(
                "python-script-v1",
                script="probe.py",
                args=[],
                dependencies=[{"source": str(tmp_path), "target": "opaque"}],
            ),
        )
    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            _candidate_profile(
                "python-script-v1", script="probe.py", args=["--alternate"]
            ),
        )


@pytest.mark.parametrize(
    "profile,extra",
    [
        ("python-script-v1", {"selectors": ["tests/test_sample.py"]}),
        ("python-module-build-v1", {"script": "probe.py", "args": []}),
    ],
)
def test_candidate_runner_rejects_irrelevant_profile_fields(
    tmp_path, profile, extra
):
    from harness.candidate_runner import CandidateRunnerError, run

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {
            "probe.py": "print('strict profile')\n",
            "pyproject.toml": "[build-system]\nrequires=[]\nbuild-backend='missing'\nbackend-path=['.']\n",
        },
    )
    spec = _candidate_profile(profile, **extra)
    if profile == "python-script-v1":
        spec.update({"script": "probe.py", "args": []})

    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(root, candidate, spec)


def test_candidate_pytest_profile_rejects_file_only_selector(tmp_path):
    from harness.candidate_runner import CandidateRunnerError, run

    root, candidate = _candidate_pytest_contract_repository(
        tmp_path, "def test_bound():\n    assert True\n"
    )

    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(
            root,
            candidate,
            _candidate_profile(
                "pytest-junit-v1",
                dependencies=_pytest_dependency_files(),
                selectors=["tests/test_sample.py"],
                evidence_type="unit_test",
            ),
        )


def test_candidate_runner_preserves_declared_outputs_on_process_failure(tmp_path):
    from harness.candidate_runner import run

    root, candidate = _candidate_runner_repository(
        tmp_path,
        {
            "probe.py": """
from pathlib import Path
Path('.candidate-output/diagnostic.txt').write_text('failure detail\\n')
raise SystemExit(7)
""",
        },
    )

    result = run(
        root,
        candidate,
        _candidate_profile("python-script-v1", script="probe.py", args=[]),
    )

    assert result["execution"]["exit_code"] == 7
    retained = root / result["execution"]["retained_output_ref"]
    assert retained.is_dir()
    assert (retained / "diagnostic.txt").read_text() == "failure detail\n"
    assert result["qualification"]["coverage_complete"] is False


def _candidate_pytest_contract_repository(
    tmp_path: Path, source: str, *, extra_files: dict[str, str] | None = None
):
    from harness.candidate_assessment import semantic_source_snapshot

    files = {"tests/test_sample.py": source, **(extra_files or {})}
    root, candidate = _candidate_runner_repository(tmp_path, files)
    harness = root / ".harness"
    harness.mkdir()
    (harness / "current-task.yaml").write_text(
        yaml.safe_dump({"task": {"id": "TASK-001", "type": "feature"}})
    )
    (harness / "requirements.yaml").write_text(
        yaml.safe_dump(
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "statement": "actual node executes",
                        "priority": "must",
                        "status": "pending",
                        "evidence": [],
                        "test_plan": {
                            "strategies": ["unit"],
                            "cases": [
                                {
                                    "id": "TC-001",
                                    "type": "happy_path",
                                    "strategy": "unit",
                                    "description": "execute bound node",
                                    "tests": ["tests/test_sample.py::test_bound"],
                                }
                            ],
                        },
                    }
                ]
            }
        )
    )
    (harness / "invariants.yaml").write_text(yaml.safe_dump({"invariants": []}))
    (harness / "plan.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "items": [
                    {
                        "id": "P-001",
                        "intent": "execute bound node",
                        "test_case_refs": ["REQ-001/TC-001"],
                    }
                ],
            }
        )
    )
    for name in ("alignment.yaml", "impact.yaml", "gate.yaml"):
        (harness / name).write_text("{}\n")
    subprocess.run(["git", "add", ".harness"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--amend", "-qm", "contract fixture"], cwd=root, check=True)
    candidate["parent"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    candidate["candidate_tree"] = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    candidate["semantic_sources"] = semantic_source_snapshot(harness)
    return root, candidate


@pytest.mark.parametrize(
    "defect",
    ["missing", "skipped", "empty", "false_type", "forged", "ambiguous"],
)
def test_candidate_pytest_profile_rejects_unqualified_junit_coverage(
    tmp_path, defect
):
    from harness.candidate_runner import CandidateRunnerError, run

    source = "def test_bound():\n    assert True\n"
    extra = None
    if defect == "skipped":
        source = "import pytest\ndef test_bound():\n    pytest.skip('not evidence')\n"
    elif defect == "empty":
        source = "def helper():\n    return True\n"
    elif defect == "ambiguous":
        source = (
            "import pytest\n"
            "@pytest.mark.parametrize('value', [1, 2])\n"
            "def test_bound(value):\n    assert value\n"
        )
        extra = {
            "tests/conftest.py": """
def pytest_collection_modifyitems(config, items):
    if not config.option.collectonly and len(items) > 1:
        items[1]._nodeid = items[0].nodeid
"""
        }
    root, candidate = _candidate_pytest_contract_repository(
        tmp_path, source, extra_files=extra
    )
    selectors = ["tests/test_sample.py::test_bound"]
    evidence_type = "unit_test"
    overrides = {}
    if defect == "missing":
        selectors = ["tests/test_sample.py::test_missing"]
    elif defect == "false_type":
        evidence_type = "contract_test"
    elif defect == "forged":
        overrides["requirements"] = ["REQ-001"]
    spec = _candidate_profile(
        "pytest-junit-v1",
        dependencies=_pytest_dependency_files(),
        selectors=selectors,
        evidence_type=evidence_type,
        **overrides,
    )

    with pytest.raises(CandidateRunnerError, match="CANDIDATE_PROOF_UNQUALIFIED"):
        run(root, candidate, spec)

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

import json
from importlib import resources
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from evidence_factory import synthetic_execution, write_evidence

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
    assert persisted_task["state"] == "ESCALATED"
    assert persisted_task["gate"]["status"] == "BLOCKED"
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
        record = {**base, "scope": "related", "covered_tests": [target], "command": f"pytest {target}",
                  "test_execution": synthetic_execution([f"{target}::test_ok"])}
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


@pytest.mark.parametrize("measurement_only", [None, "fast-red-unit-test.json", "fast-green-unit-test.json", "unit-test.json"])
def test_fast_gate_requires_only_task_phase_proof(tmp_path, measurement_only):
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
    gate_path = h / "gate.yaml"
    gate = yaml.safe_load(gate_path.read_text())
    gate["gate"]["fast"] = {"verification": {"build": "required", "unit_test": "required"}}
    gate_path.write_text(yaml.safe_dump(gate))
    if measurement_only:
        path = h / "evidence" / measurement_only
        record = json.loads(path.read_text())
        record["type"] = "custom"
        record.pop("test_execution")
        path.write_text(json.dumps(record))  # Deliberately malformed unit input, never a native receipt.

    status, blockers = __import__(
        "harness.quality_gate", fromlist=["run_gate"]
    ).run_gate(h)

    if measurement_only:
        assert status == "BLOCKED"
        assert any(item.code in {"FAST_REGRESSION_EVIDENCE_MISSING", "FAST_REPOSITORY_VERIFICATION_MISSING"} for item in blockers)
    else:
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


def test_supplied_workspace_is_the_only_fingerprint(tmp_path, monkeypatch):
    from harness import quality_gate
    from harness.workspace import snapshot

    h = make_harness(tmp_path)
    current = snapshot()

    def fail(*_args, **_kwargs):
        raise AssertionError("gate walked the product tree again")

    monkeypatch.setattr(quality_gate, "snapshot", fail)
    assessment = quality_gate.assess_gate(h, allow_preflight=True, workspace=current)

    assert assessment.status in {"PASS", "BLOCKED"}


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


def _regression_policy_fixture(tmp_path, profile):
    h = make_harness(tmp_path)
    if profile == "fast":
        task_path = h / "current-task.yaml"
        task = yaml.safe_load(task_path.read_text())
        task["git"]["base_commit"] = HEAD
        task["risk"] = {
            "level": "Q1", "profile": "FAST", "dimensions": SAFE_DIMENSIONS,
            "escalation_history": [],
            "user_changes": {"paths": [], "fingerprint": "sha256:" + "0" * 64},
        }
        task_path.write_text(yaml.safe_dump(task))
        (h / "risk-boundaries.yaml").write_text("boundaries:\n  q2: [never/**]\n  q3: [never/**]\n")
    return h


@pytest.mark.parametrize("profile", ["full", "fast"])
@pytest.mark.parametrize("value", [1, 4])
def test_nonzero_regression_policy_rejected_before_gate_evaluation(tmp_path, profile, value):
    h = _regression_policy_fixture(tmp_path, profile)
    assert _gate(h).returncode in (0, 1), "zero-default control must reach Gate evaluation"
    path = h / "gate.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["gate"]["regression"]["confirmed_finding_without_test"] = value
    path.write_text(yaml.safe_dump(policy))
    before_task, before_config = (h / "current-task.yaml").read_bytes(), path.read_bytes()
    result = _gate(h)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "gate.schema.json at gate.regression.confirmed_finding_without_test" in result.stderr
    assert "0 was expected" in result.stderr
    assert (h / "current-task.yaml").read_bytes() == before_task
    assert path.read_bytes() == before_config


@pytest.mark.parametrize("value", [1, 10])
def test_missing_regression_blocker_never_uses_legacy_allowance(value):
    from harness.quality_gate import _defect_finding_blockers

    # Defensive helper subsets, NOT a full-Gate bypass reproduction: schema/proofs
    # reject these incomplete records before this helper in real Gate evaluation.
    findings = [
        {"id": f"FND-{n:03d}", "severity": "minor", "status": "CONFIRMED", "category": "adversarial"}
        for n in (1, 2)
    ]
    blockers = _defect_finding_blockers(findings, {"regression": {"confirmed_finding_without_test": value}})
    assert [(b.code, b.finding_id) for b in blockers] == [
        ("IMPLEMENTATION_INCOMPLETE", "FND-001"),
        ("IMPLEMENTATION_INCOMPLETE", "FND-002"),
    ]


@pytest.mark.parametrize("profile", ["full", "fast"])
@pytest.mark.parametrize("mode", ["absent", "empty", "zero", "numeric_zero"])
def test_zero_or_omitted_regression_policy_keeps_gate_behavior(tmp_path, profile, mode):
    h = _regression_policy_fixture(tmp_path, profile)
    baseline = _gate(h)
    assert baseline.returncode in (0, 1)
    path = h / "gate.yaml"
    policy = yaml.safe_load(path.read_text())
    if mode == "absent":
        policy["gate"].pop("regression")
    elif mode == "empty":
        policy["gate"]["regression"] = {}
    else:
        policy["gate"]["regression"]["confirmed_finding_without_test"] = 0.0 if mode == "numeric_zero" else 0
    path.write_text(yaml.safe_dump(policy))
    current = _gate(h)
    assert (current.returncode, current.stdout, current.stderr) == (
        baseline.returncode, baseline.stdout, baseline.stderr
    )


@pytest.mark.parametrize("profile", ["full", "fast"])
@pytest.mark.parametrize("value", [-1, "0", False, None])
def test_invalid_regression_policy_types_stay_rejected(tmp_path, profile, value):
    h = _regression_policy_fixture(tmp_path, profile)
    path = h / "gate.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["gate"]["regression"]["confirmed_finding_without_test"] = value
    path.write_text(yaml.safe_dump(policy))
    result = _gate(h)
    assert result.returncode == 2
    assert "gate.schema.json at gate.regression.confirmed_finding_without_test" in result.stderr


@pytest.mark.parametrize("profile", ["full", "fast"])
def test_native_gate_nonzero_policy_preserves_task_and_config(tmp_path, monkeypatch, capsys, profile):
    from harness import controlplane

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "base"], check=True)
    h = _regression_policy_fixture(tmp_path, profile)
    path = h / "gate.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["gate"]["regression"]["confirmed_finding_without_test"] = 3
    path.write_text(yaml.safe_dump(policy))
    before_task, before_config = (h / "current-task.yaml").read_bytes(), path.read_bytes()
    monkeypatch.chdir(tmp_path)
    assert controlplane.cmd_gate() == 2
    output = capsys.readouterr()
    assert "INVALID_HARNESS_STATE" in output.err
    assert "gate.schema.json at gate.regression.confirmed_finding_without_test" in output.err
    assert (h / "current-task.yaml").read_bytes() == before_task
    assert path.read_bytes() == before_config


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


def _fast_finding_harness(tmp_path):
    from harness.workspace import protected_paths_fingerprint

    h = make_harness(tmp_path)
    task_path = h / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["git"]["base_commit"] = HEAD
    task["risk"] = {
        "level": "Q1",
        "profile": "FAST",
        "dimensions": SAFE_DIMENSIONS,
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": protected_paths_fingerprint(())},
    }
    task_path.write_text(yaml.safe_dump(task))
    (h / "risk-boundaries.yaml").write_text(
        "boundaries:\n  q2: [never/**]\n  q3: [never/**]\n"
    )
    write_evidence(REPO, h, "unit_test", exit_code=1, name="fast-red-unit-test.json")
    write_evidence(REPO, h, "unit_test", name="fast-green-unit-test.json")
    return h


@pytest.mark.parametrize("status", ["PROPOSED", "REPRODUCING"])
@pytest.mark.parametrize("severity", ["critical", "major"])
def test_fast_gate_rejects_open_defect_findings(tmp_path, status, severity):
    h = _fast_finding_harness(tmp_path)
    finding = finding_doc("FND-0104", severity, status)
    (h / "findings/FND-0104.yaml").write_text(yaml.safe_dump(finding))

    from harness.quality_gate import run_gate

    gate_status, blockers = run_gate(h)

    assert gate_status == "BLOCKED"
    assert any(
        b.code == "FINDING_OPEN" and b.finding_id == "FND-0104" for b in blockers
    )


@pytest.mark.parametrize("path", ["", "tests/test_fix.py::test_regression"])
def test_fast_gate_rejects_confirmed_finding_without_valid_red_proof(tmp_path, path):
    h = _fast_finding_harness(tmp_path)
    finding = finding_doc(
        "FND-0104",
        "minor",
        "CONFIRMED",
        test=path,
        confirmed_at="2026-01-01T00:00:00+00:00",
        regression_test={"path": path, "red_evidence": "missing-red.json"},
    )
    (h / "findings/FND-0104.yaml").write_text(yaml.safe_dump(finding))

    result = _gate(h)

    assert result.returncode != 0
    assert "red evidence invalid" in result.stderr or "regression test" in result.stdout


@pytest.mark.parametrize(
    "severity,status,extra",
    [
        ("minor", "PROPOSED", {}),
        (
            "major",
            "REJECTED",
            {"attempts": ["reproduced"], "rejection_reason": "not a defect"},
        ),
    ],
)
def test_fast_gate_preserves_nonblocking_finding_policy(
    tmp_path, severity, status, extra
):
    h = _fast_finding_harness(tmp_path)
    finding = finding_doc("FND-0104", severity, status, **extra)
    (h / "findings/FND-0104.yaml").write_text(yaml.safe_dump(finding))

    assert _gate(h).returncode == 0


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("audit_status", ["CONFIRMED", "CLOSED"])
def test_shared_finding_checks_preserve_closed_alignment_audit(
    tmp_path, fast, audit_status
):
    h = _fast_finding_harness(tmp_path) if fast else make_harness(tmp_path)
    finding = {
        "id": "FND-0104",
        "category": "alignment",
        "task_id": "TASK-001",
        "type": "contract_changed",
        "severity": "blocking",
        "status": audit_status,
        "detected_during": "IMPLEMENTING",
        "reason_code": "CONTRACT_CHANGED",
        "boundary_ref": "alignment.yaml",
        "expected_hash": "sha256:" + "0" * 64,
        "actual_hash": "sha256:" + "1" * 64,
    }
    (h / "findings/FND-0104.yaml").write_text(yaml.safe_dump(finding))
    try:
        result = _gate(h)
    except KeyError:
        pytest.fail("alignment audit incorrectly requires defect regression proof")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("green_nodes,accepted", [
    (["tests/fixture.py::test_fixture"], True),
    (["tests/fixture.py::test_unrelated"], False),
    (["tests/fixture.py::test_fixture[other]"], False),
])
def test_fast_gate_requires_green_for_actual_red_failures(tmp_path, green_nodes, accepted):
    h = _fast_finding_harness(tmp_path)
    path = h / "evidence/fast-green-unit-test.json"
    record = json.loads(path.read_text())
    record["test_execution"] = synthetic_execution(green_nodes)
    path.write_text(json.dumps(record))

    result = _gate(h)

    assert (result.returncode == 0) is accepted, result.stdout + result.stderr
    if not accepted:
        assert "FAST" in result.stdout and "regression" in result.stdout


@pytest.mark.parametrize("red_nodes,green_nodes,accepted", [
    (["tests/fixture.py::test_fixture[a]"], ["tests/fixture.py::test_fixture[a]"], True),
    (["tests/fixture.py::test_fixture[a]"], ["tests/fixture.py::test_fixture[b]"], False),
    (["tests/fixture.py::test_fixture", "tests/fixture.py::test_second"],
     ["tests/fixture.py::test_fixture"], False),
])
def test_fast_gate_pairs_each_red_parameter_and_failure(tmp_path, red_nodes, green_nodes, accepted):
    h = _fast_finding_harness(tmp_path)
    for phase, nodes, exit_code in [("red", red_nodes, 1), ("green", green_nodes, 0)]:
        path = h / f"evidence/fast-{phase}-unit-test.json"
        record = json.loads(path.read_text())
        record["test_execution"] = synthetic_execution(nodes, exit_code)
        path.write_text(json.dumps(record))
    assert (_gate(h).returncode == 0) is accepted


@pytest.mark.parametrize("retry", ["success", "failed", "stale", "malformed", "wrong_type", "unrelated_name"])
def test_fast_gate_consumes_canonical_latest_build_receipt(tmp_path, retry):
    h = _fast_finding_harness(tmp_path)
    first = h / "evidence/build.json"
    record = json.loads(first.read_text())
    first.write_text(json.dumps({**record, "exit_code": 1}))
    if retry == "failed":
        record["exit_code"] = 1
    elif retry == "stale":
        record["workspace_fingerprint"] = "sha256:" + "0" * 64
    elif retry == "wrong_type":
        record["type"] = "custom"
    name = "build-other.json" if retry == "unrelated_name" else "build-2.json"
    (h / "evidence" / name).write_text("{" if retry == "malformed" else json.dumps(record))

    result = _gate(h)

    assert (result.returncode == 0) is (retry == "success"), result.stdout + result.stderr


def test_fast_gate_does_not_ignore_a_later_failed_build(tmp_path):
    h = _fast_finding_harness(tmp_path)
    record = json.loads((h / "evidence/build.json").read_text())
    (h / "evidence/build-2.json").write_text(json.dumps({**record, "exit_code": 1}))
    assert _gate(h).returncode == 1

import yaml

from harness.quality_gate import validate_schema
from test_cli_decision import cli, setup


def test_interface_review_proposal_publishes_interface_finding(tmp_path):
    """Break caught: failed interface review has no persisted Finding lifecycle object."""
    setup(tmp_path)
    assert (
        cli(
            tmp_path,
            "interface",
            "declare",
            "--name",
            "api",
            "--kind",
            "cli",
            "--consumer",
            "agent",
            "--input",
            "input",
            "--output",
            "output",
            "--error",
            "error",
            "--compatibility",
            "compatible",
            "--rationale",
            "additive",
        ).returncode
        == 0
    )
    task_path = tmp_path / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = "REVIEWING"
    task_path.write_text(yaml.safe_dump(task))
    source = tmp_path / "interface-review.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "task": "TASK-042",
                "contracts": ["INT-001"],
                "checks": {
                    "boundary": "fail",
                    "dto": "pass",
                    "errors": "pass",
                    "dependency": "pass",
                    "compatibility": "pass",
                    "tests": "pass",
                },
                "proposals": [
                    {
                        "target": "REQ-005",
                        "severity": "major",
                        "scenario": "public DTO exposes persistence field",
                        "location": {
                            "file": "src/harness/interface_contract.py",
                            "line": 1,
                        },
                    }
                ],
            }
        )
    )

    result = cli(tmp_path, "review", "interface", "--file", str(source))

    assert result.returncode == 0, result.stderr
    finding = yaml.safe_load(
        (tmp_path / ".harness" / "findings" / "FND-001.yaml").read_text()
    )
    assert finding["category"] == "interface"

    repeat = cli(tmp_path, "review", "interface", "--file", str(source))

    assert repeat.returncode == 0, repeat.stderr
    assert [path.name for path in (tmp_path / ".harness" / "findings").glob("FND-*.yaml")] == [
        "FND-001.yaml"
    ]


def test_interface_review_publish_failure_leaves_no_canonical_artifacts(tmp_path, monkeypatch):
    """Break caught: failed multi-artifact publication leaves an open Finding behind."""
    from harness import interface_review

    setup(tmp_path)
    assert cli(
        tmp_path, "interface", "declare", "--name", "api", "--kind", "cli",
        "--consumer", "agent", "--input", "input", "--output", "output",
        "--error", "error", "--compatibility", "compatible", "--rationale", "additive",
    ).returncode == 0
    source = tmp_path / "interface-review.yaml"
    source.write_text(yaml.safe_dump({
        "task": "TASK-042", "contracts": ["INT-001"],
        "checks": {"boundary": "fail", "dto": "pass", "errors": "pass", "dependency": "pass", "compatibility": "pass", "tests": "pass"},
        "proposals": [{"target": "REQ-005", "severity": "major", "scenario": "leak", "location": {"file": "x.py"}}],
    }))

    def fail_publish(*_args, **_kwargs):
        raise OSError("injected publish failure")

    monkeypatch.setattr(interface_review, "publish", fail_publish)
    with __import__("pytest").raises(OSError, match="injected publish failure"):
        interface_review.write_review(tmp_path / ".harness", source, task_id="TASK-042")

    assert not list((tmp_path / ".harness/findings").glob("FND-*.yaml"))
    assert not (tmp_path / ".harness/evidence/interface-review.json").exists()


def test_interface_review_persists_contract_bound_review_evidence(tmp_path):
    """Break caught: interface review is not persisted against reviewed contract."""
    setup(tmp_path)
    assert (
        cli(
            tmp_path,
            "interface",
            "declare",
            "--name",
            "api",
            "--kind",
            "cli",
            "--consumer",
            "agent",
            "--input",
            "input",
            "--output",
            "output",
            "--error",
            "error",
            "--compatibility",
            "compatible",
            "--rationale",
            "additive",
        ).returncode
        == 0
    )
    task_path = tmp_path / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = "REVIEWING"
    task_path.write_text(yaml.safe_dump(task))
    source = tmp_path / "interface-review.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "task": "TASK-042",
                "contracts": ["INT-001"],
                "checks": {
                    "boundary": "pass",
                    "dto": "pass",
                    "errors": "pass",
                    "dependency": "pass",
                    "compatibility": "pass",
                    "tests": "pass",
                },
                "proposals": [],
            }
        )
    )

    result = cli(tmp_path, "review", "interface", "--file", str(source))

    assert result.returncode == 0, result.stderr
    record = __import__("json").loads(
        (tmp_path / ".harness" / "evidence" / "interface-review.json").read_text()
    )
    assert record["contracts"] == ["INT-001"]


def test_interface_finding_schema_accepts_closed_lifecycle_status(tmp_path):
    """Break caught: closed Interface Finding remains schema-valid for Gate loading."""
    finding = {
        "id": "FND-001",
        "kind": "requirement_violation",
        "category": "interface",
        "target": "REQ-001",
        "scenario": "resolved public contract violation",
        "severity": "major",
        "status": "CLOSED",
        "location": {"file": "src/harness/interface_review.py", "line": 1},
    }

    validate_schema(finding, "interface-finding.schema.json", tmp_path / "finding.yaml")

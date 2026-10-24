"""TASK-004: deterministic finding lifecycle control plane."""

import json
import shlex
import subprocess
import sys
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent

def cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(tmp_path, *, trusted_scope=False):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    cli(tmp_path, "init")
    if trusted_scope:
        bound = cli(tmp_path, "task", "migrate-id", "TASK-001")
        assert bound.returncode == 0, bound.stderr
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "import os\ndef test_x():\n    assert os.environ.get('HARNESS_FINDING_RED') != '1'\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    h = tmp_path / ".harness"
    f = {
        "id": "FND-001",
        "category": "adversarial",
        "kind": "failure_scenario",
        "target": "REQ-001",
        "scenario": "attack",
        "severity": "critical",
        "status": "PROPOSED",
    }
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(f))
    # Lifecycle fixtures use real child reports, never synthetic assertion manifests.
    # Named aliases preserve original native receipts and copy their exact bytes.
    for phase in ("red", "green", "full"):
        before = set((h / "evidence").glob("*.json"))
        command = (f"HARNESS_FINDING_RED={1 if phase == 'red' else 0} "
                   f"{shlex.quote(sys.executable)} -B -m pytest -q -p no:cacheprovider tests/test_x.py")
        result = cli(tmp_path, "evidence", "run", "--type", "unit_test", "--finding", "FND-001",
                     "--phase", phase, "--test", "tests/test_x.py::test_x",
                     "--covered-test", "tests/test_x.py::test_x", "--command", command)
        assert result.returncode == 0, result.stdout + result.stderr
        created = set((h / "evidence").glob("*.json")) - before
        assert len(created) == 1
        (h / "evidence" / f"{phase}.json").write_bytes(created.pop().read_bytes())
    if not trusted_scope:
        (h / "impact.yaml").write_text(
            yaml.safe_dump({"impact": {"required_tests": ["tests/test_x.py::test_x"]}})
        )
    return h


def status(h):
    return yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())["status"]


def test_cli_enforces_full_proof_chain(tmp_path):
    h = setup(tmp_path)
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "REPRODUCING",
            "--attempt",
            "red test created",
        ).returncode
        == 0
    )
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "CONFIRMED",
            "--test",
            "tests/test_x.py::test_x",
            "--evidence",
            "red.json",
        ).returncode
        == 0
    )
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXING").returncode == 0
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "FIXED",
            "--evidence",
            "green.json",
        ).returncode
        == 0
    )
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "VERIFIED",
            "--evidence",
            "full.json",
        ).returncode
        == 0
    )
    assert cli(tmp_path, "finding", "transition", "FND-001", "CLOSED").returncode == 0
    assert status(h) == "CLOSED"


def test_alignment_finding_can_complete_existing_lifecycle(tmp_path):
    h = setup(tmp_path)
    finding = {
        "id": "FND-001", "category": "alignment", "task_id": "TASK-001",
        "type": "contract_changed", "severity": "blocking", "status": "PROPOSED",
        "detected_during": "IMPLEMENTING", "expected_hash": "sha256:" + "0" * 64,
        "actual_hash": "sha256:" + "1" * 64,
        "reason_code": "SCOPE_DRIFT_PERMISSION", "boundary_ref": "DEC-001",
    }
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(finding))

    for target, args in (
        ("REPRODUCING", ("--attempt", "reproduce")),
        ("CONFIRMED", ("--test", "tests/test_x.py::test_x", "--evidence", "red.json")),
        ("FIXING", ()),
        ("FIXED", ("--evidence", "green.json")),
        ("VERIFIED", ("--evidence", "full.json")),
        ("CLOSED", ()),
    ):
        assert cli(tmp_path, "finding", "transition", "FND-001", target, *args).returncode == 0
    assert status(h) == "CLOSED"


def test_diag_cli_lifecycle_uses_passing_review_without_red_green(tmp_path):
    h = setup(tmp_path)
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    finding.update(
        {
            "category": "diagnosability",
            "reason_code": "DIAG_MISSING_BUSINESS_ID",
            "severity": "major",
            "location": {"file": "x.py"},
            "compliance": {
                "evidence_kind": "static_compliance",
                "required_checks": ["business_keys"],
            },
        }
    )
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(finding))
    review = json.loads((h / "evidence" / "full.json").read_text())
    review.update(
        {"type": "diagnosability_review", "checks": {"business_keys": "pass"}}
    )
    (h / "evidence" / "diagnosability-review.json").write_text(json.dumps(review))
    for target, args in (
        ("REPRODUCING", ("--attempt", "review")),
        ("CONFIRMED", ()),
        ("FIXING", ()),
        ("FIXED", ()),
        ("VERIFIED", ("--evidence", "diagnosability-review.json")),
    ):
        assert (
            cli(tmp_path, "finding", "transition", "FND-001", target, *args).returncode
            == 0
        )


def test_resume_review_routes_fixed_finding_to_reviewing(tmp_path):
    h = setup(tmp_path)
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    finding.update(
        {
            "status": "FIXED",
            "category": "diagnosability",
            "reason_code": "DIAG_MISSING_BUSINESS_ID",
            "location": {"file": "x.py"},
            "compliance": {
                "evidence_kind": "static_compliance",
                "required_checks": ["business_keys"],
            },
        }
    )
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(finding))
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["state"] = "REPRODUCING"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = cli(tmp_path, "finding", "resume-review", "FND-001")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load((h / "current-task.yaml").read_text())["state"] == "REVIEWING"


def test_generic_transition_requires_finding_resume_review(tmp_path):
    h = setup(tmp_path, trusted_scope=True)
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    finding.update(
        {
            "status": "FIXED",
            "category": "diagnosability",
            "reason_code": "DIAG_MISSING_BUSINESS_ID",
            "location": {"file": "x.py"},
            "compliance": {
                "evidence_kind": "static_compliance",
                "required_checks": ["business_keys"],
            },
        }
    )
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(finding))
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["state"] = "REPRODUCING"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = cli(tmp_path, "transition", "REVIEWING")

    assert result.returncode == 1
    assert "FINDING_REVIEW_RESUME_REQUIRED" in result.stderr


def test_confirmed_rejects_evidence_reference_outside_canonical_directory(tmp_path):
    h = setup(tmp_path)
    (h / "history").mkdir(exist_ok=True)
    (h / "history" / "red.json").write_bytes((h / "evidence" / "red.json").read_bytes())
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "REPRODUCING",
            "--attempt",
            "red test created",
        ).returncode
        == 0
    )

    result = cli(
        tmp_path,
        "finding",
        "transition",
        "FND-001",
        "CONFIRMED",
        "--test",
        "tests/test_x.py::test_x",
        "--evidence",
        "../history/red.json",
    )

    assert result.returncode == 2
    assert "EVIDENCE_REFERENCE_INVALID" in result.stderr
    assert status(h) == "REPRODUCING"


def test_confirmed_rejects_unstructured_failed_evidence(tmp_path):
    h = setup(tmp_path)
    red_path = h / "evidence" / "red.json"
    red = json.loads(red_path.read_text())
    del red["subject"], red["test"]
    red_path.write_text(json.dumps(red))
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "REPRODUCING",
            "--attempt",
            "red test created",
        ).returncode
        == 0
    )

    result = cli(
        tmp_path,
        "finding",
        "transition",
        "FND-001",
        "CONFIRMED",
        "--test",
        "tests/test_x.py::test_x",
        "--evidence",
        "red.json",
    )

    assert result.returncode == 2
    assert "FINDING_SUBJECT_MISMATCH" in result.stderr
    assert status(h) == "REPRODUCING"


def test_fixed_rejects_green_evidence_for_different_test(tmp_path):
    h = setup(tmp_path)
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "REPRODUCING",
            "--attempt",
            "red test created",
        ).returncode
        == 0
    )
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "CONFIRMED",
            "--test",
            "tests/test_x.py::test_x",
            "--evidence",
            "red.json",
        ).returncode
        == 0
    )
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXING").returncode == 0
    # A truthful execution of the wrong test, not relabelled/tampered proof of test_x.
    (tmp_path / "tests/test_other.py").write_text("def test_other():\n    assert True\n")
    wrong = cli(tmp_path, "evidence", "run", "--type", "custom", "--finding", "FND-001",
                "--phase", "green", "--test", "tests/test_other.py::test_other", "--command",
                f"{shlex.quote(sys.executable)} -B -m pytest -q -p no:cacheprovider tests/test_other.py")
    assert wrong.returncode == 0, wrong.stdout + wrong.stderr

    result = cli(
        tmp_path,
        "finding",
        "transition",
        "FND-001",
        "FIXED",
        "--evidence",
        "FND-001-green-custom.json",
    )

    assert result.returncode == 2
    assert "REGRESSION_TEST_MISMATCH" in result.stderr
    assert status(h) == "FIXING"


def test_critical_finding_accepts_related_closure_evidence(tmp_path):
    h = setup(tmp_path)
    full = json.loads((h / "evidence" / "full.json").read_text())
    full["scope"] = "related"
    full["covered_tests"] = ["tests/test_x.py::test_x"]
    (h / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "impact": {
                    "required_tests": ["tests/test_x.py::test_x"],
                }
            }
        )
    )
    (h / "evidence" / "full.json").write_text(json.dumps(full))
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "REPRODUCING",
            "--attempt",
            "red test created",
        ).returncode
        == 0
    )
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "CONFIRMED",
            "--test",
            "tests/test_x.py::test_x",
            "--evidence",
            "red.json",
        ).returncode
        == 0
    )
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXING").returncode == 0
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "FIXED",
            "--evidence",
            "green.json",
        ).returncode
        == 0
    )
    result = cli(
        tmp_path,
        "finding",
        "transition",
        "FND-001",
        "VERIFIED",
        "--evidence",
        "full.json",
    )
    assert result.returncode == 0


def test_critical_finding_accepts_approved_related_closure(tmp_path):
    h = setup(tmp_path)
    full = json.loads((h / "evidence" / "full.json").read_text())
    full["scope"] = "related"
    full["covered_tests"] = ["tests/test_x.py::test_x"]
    (h / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "impact": {
                    "required_tests": ["tests/test_x.py::test_x"],
                    "full_suite": {"recommended": True},
                }
            }
        )
    )
    (h / "evidence" / "full.json").write_text(json.dumps(full))
    for args in (
        ("REPRODUCING", "--attempt", "red"),
        ("CONFIRMED", "--test", "tests/test_x.py::test_x", "--evidence", "red.json"),
        ("FIXING",),
        ("FIXED", "--evidence", "green.json"),
    ):
        assert cli(tmp_path, "finding", "transition", "FND-001", *args).returncode == 0
    result = cli(
        tmp_path,
        "finding",
        "transition",
        "FND-001",
        "VERIFIED",
        "--evidence",
        "full.json",
        "--critical-related-approved",
    )
    assert result.returncode == 0, result.stderr
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    assert finding["closure"]["critical_related_approved"] is True


def test_cli_preserves_finding_red_and_green_evidence_separately(tmp_path):
    h = setup(tmp_path)
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "REPRODUCING",
            "--attempt",
            "red",
        ).returncode
        == 0
    )
    red = cli(
        tmp_path,
        "evidence",
        "--type",
        "custom",
        "--finding",
        "FND-001",
        "--phase",
        "red",
        "--test",
        "tests/test_x.py::test_x",
        "--command",
        f"HARNESS_FINDING_RED=1 {shlex.quote(sys.executable)} -B -m pytest -q -p no:cacheprovider tests/test_x.py",
    )
    assert red.returncode == 0, red.stderr
    red_ref = "FND-001-red-custom.json"
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "CONFIRMED",
            "--test",
            "tests/test_x.py::test_x",
            "--evidence",
            red_ref,
        ).returncode
        == 0
    )
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXING").returncode == 0
    green = cli(
        tmp_path,
        "evidence",
        "--type",
        "custom",
        "--finding",
        "FND-001",
        "--phase",
        "green",
        "--test",
        "tests/test_x.py::test_x",
        "--command",
        f"HARNESS_FINDING_RED=0 {shlex.quote(sys.executable)} -B -m pytest -q -p no:cacheprovider tests/test_x.py",
    )
    assert green.returncode == 0, green.stderr
    green_ref = "FND-001-green-custom.json"
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "FIXED",
            "--evidence",
            green_ref,
        ).returncode
        == 0
    )
    assert (h / "evidence" / red_ref).is_file()
    assert (h / "evidence" / green_ref).is_file()
    assert json.loads((h / "evidence" / red_ref).read_text())["exit_code"] != 0
    assert json.loads((h / "evidence" / green_ref).read_text())["exit_code"] == 0


def test_cli_rejects_skip(tmp_path):
    h = setup(tmp_path)
    assert (
        cli(
            tmp_path,
            "finding",
            "transition",
            "FND-001",
            "VERIFIED",
            "--evidence",
            "full.json",
        ).returncode
        == 1
    )
    assert status(h) == "PROPOSED"

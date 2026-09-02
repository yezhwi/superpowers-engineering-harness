"""TASK-004: deterministic finding lifecycle control plane."""
import json
import subprocess
import sys
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from collect_evidence import workspace_fingerprint

def cli(cwd, *args):
    return subprocess.run([sys.executable, "-m", "harness.cli", *args], cwd=cwd,
      capture_output=True, text=True, env={"PYTHONPATH": str(REPO / "src"), "PATH":"/usr/bin:/bin"})

def setup(tmp_path):
    subprocess.run(["git","init","-q"], cwd=tmp_path, check=True)
    cli(tmp_path,"init"); subprocess.run(["git","add","-A"],cwd=tmp_path,check=True)
    subprocess.run(["git","commit","-qm","init"],cwd=tmp_path,check=True)
    head=subprocess.run(["git","rev-parse","HEAD"],cwd=tmp_path,capture_output=True,text=True).stdout.strip()
    h=tmp_path/".harness"
    f={"id":"FND-001","kind":"failure_scenario","target":"REQ-001","scenario":"attack","severity":"critical","status":"PROPOSED"}
    (h/"findings"/"fnd-001.yaml").write_text(yaml.safe_dump(f))
    fingerprint = workspace_fingerprint(tmp_path)
    for name,code in [("red.json",1),("green.json",0),("full.json",0)]:
      evidence = {"type":"custom","timestamp":"2026-01-01T00:00:00+00:00","command":"test","exit_code":code,"commit":head,"workspace_fingerprint":fingerprint,"workspace_fingerprint_after":fingerprint}
      if name != "full.json":
        evidence.update({"subject":{"kind":"finding","id":"FND-001"},"test":{"node_id":"tests/test_x.py::test_x"}})
      else:
        evidence.update({"scope":"full_suite","covered_tests":[]})
      (h/"evidence"/name).write_text(json.dumps(evidence))
    return h

def status(h): return yaml.safe_load((h/"findings"/"fnd-001.yaml").read_text())["status"]

def test_cli_enforces_full_proof_chain(tmp_path):
    h=setup(tmp_path)
    assert cli(tmp_path,"finding","transition","FND-001","REPRODUCING","--attempt","red test created").returncode==0
    assert cli(tmp_path,"finding","transition","FND-001","CONFIRMED","--test","tests/test_x.py::test_x","--evidence","red.json").returncode==0
    assert cli(tmp_path,"finding","transition","FND-001","FIXING").returncode==0
    assert cli(tmp_path,"finding","transition","FND-001","FIXED","--evidence","green.json").returncode==0
    assert cli(tmp_path,"finding","transition","FND-001","VERIFIED","--evidence","full.json").returncode==0
    assert cli(tmp_path,"finding","transition","FND-001","CLOSED").returncode==0
    assert status(h)=="CLOSED"

def test_diag_cli_lifecycle_uses_passing_review_without_red_green(tmp_path):
    h = setup(tmp_path)
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    finding.update({"category": "diagnosability", "reason_code": "DIAG_MISSING_BUSINESS_ID", "severity": "major", "location": {"file": "x.py"}, "compliance": {"evidence_kind": "static_compliance", "required_checks": ["business_keys"]}})
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(finding))
    review = json.loads((h / "evidence" / "full.json").read_text())
    review.update({"type": "diagnosability_review", "checks": {"business_keys": "pass"}})
    (h / "evidence" / "diagnosability-review.json").write_text(json.dumps(review))
    for target, args in (("REPRODUCING", ("--attempt", "review")), ("CONFIRMED", ()), ("FIXING", ()), ("FIXED", ()), ("VERIFIED", ("--evidence", "diagnosability-review.json"))):
        assert cli(tmp_path, "finding", "transition", "FND-001", target, *args).returncode == 0


def test_resume_review_routes_fixed_finding_to_reviewing(tmp_path):
    h = setup(tmp_path)
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    finding.update({"status": "FIXED", "category": "diagnosability", "reason_code": "DIAG_MISSING_BUSINESS_ID", "location": {"file": "x.py"}, "compliance": {"evidence_kind": "static_compliance", "required_checks": ["business_keys"]}})
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(finding))
    task = yaml.safe_load((h / "current-task.yaml").read_text()); task["state"] = "REPRODUCING"; (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = cli(tmp_path, "finding", "resume-review", "FND-001")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load((h / "current-task.yaml").read_text())["state"] == "REVIEWING"


def test_generic_transition_requires_finding_resume_review(tmp_path):
    h = setup(tmp_path)
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    finding.update({"status": "FIXED", "category": "diagnosability", "reason_code": "DIAG_MISSING_BUSINESS_ID", "location": {"file": "x.py"}, "compliance": {"evidence_kind": "static_compliance", "required_checks": ["business_keys"]}})
    (h / "findings" / "fnd-001.yaml").write_text(yaml.safe_dump(finding))
    task = yaml.safe_load((h / "current-task.yaml").read_text()); task["state"] = "REPRODUCING"; (h / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = cli(tmp_path, "transition", "REVIEWING")

    assert result.returncode == 1
    assert "FINDING_REVIEW_RESUME_REQUIRED" in result.stderr


def test_confirmed_rejects_evidence_reference_outside_canonical_directory(tmp_path):
    h = setup(tmp_path)
    (h / "history").mkdir(exist_ok=True)
    (h / "history" / "red.json").write_bytes((h / "evidence" / "red.json").read_bytes())
    assert cli(tmp_path, "finding", "transition", "FND-001", "REPRODUCING", "--attempt", "red test created").returncode == 0

    result = cli(tmp_path, "finding", "transition", "FND-001", "CONFIRMED", "--test", "tests/test_x.py::test_x", "--evidence", "../history/red.json")

    assert result.returncode == 2
    assert "EVIDENCE_REFERENCE_INVALID" in result.stderr
    assert status(h) == "REPRODUCING"


def test_confirmed_rejects_unstructured_failed_evidence(tmp_path):
    h = setup(tmp_path)
    red_path = h / "evidence" / "red.json"
    red = json.loads(red_path.read_text())
    del red["subject"], red["test"]
    red_path.write_text(json.dumps(red))
    assert cli(tmp_path, "finding", "transition", "FND-001", "REPRODUCING", "--attempt", "red test created").returncode == 0

    result = cli(tmp_path, "finding", "transition", "FND-001", "CONFIRMED", "--test", "tests/test_x.py::test_x", "--evidence", "red.json")

    assert result.returncode == 2
    assert "FINDING_SUBJECT_MISMATCH" in result.stderr
    assert status(h) == "REPRODUCING"


def test_fixed_rejects_green_evidence_for_different_test(tmp_path):
    h = setup(tmp_path)
    assert cli(tmp_path, "finding", "transition", "FND-001", "REPRODUCING", "--attempt", "red test created").returncode == 0
    assert cli(tmp_path, "finding", "transition", "FND-001", "CONFIRMED", "--test", "tests/test_x.py::test_x", "--evidence", "red.json").returncode == 0
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXING").returncode == 0
    green_path = h / "evidence" / "green.json"
    green = json.loads(green_path.read_text())
    green["test"] = {"node_id": "tests/test_other.py::test_other"}
    green_path.write_text(json.dumps(green))

    result = cli(tmp_path, "finding", "transition", "FND-001", "FIXED", "--evidence", "green.json")

    assert result.returncode == 2
    assert "REGRESSION_TEST_MISMATCH" in result.stderr
    assert status(h) == "FIXING"


def test_critical_finding_rejects_related_closure_evidence(tmp_path):
    h = setup(tmp_path)
    full = json.loads((h / "evidence" / "full.json").read_text())
    full["scope"] = "related"
    full["covered_tests"] = ["tests/test_x.py::test_x"]
    (h / "impact.yaml").write_text(yaml.safe_dump({"impact": {"required_tests": ["tests/test_x.py::test_x"], "full_suite": {"recommended": False}}}))
    (h / "evidence" / "full.json").write_text(json.dumps(full))
    assert cli(tmp_path, "finding", "transition", "FND-001", "REPRODUCING", "--attempt", "red test created").returncode == 0
    assert cli(tmp_path, "finding", "transition", "FND-001", "CONFIRMED", "--test", "tests/test_x.py::test_x", "--evidence", "red.json").returncode == 0
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXING").returncode == 0
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXED", "--evidence", "green.json").returncode == 0
    result = cli(tmp_path, "finding", "transition", "FND-001", "VERIFIED", "--evidence", "full.json")
    assert result.returncode == 2
    assert "CRITICAL_RELATED_APPROVAL_REQUIRED" in result.stderr


def test_critical_finding_accepts_approved_related_closure(tmp_path):
    h = setup(tmp_path)
    full = json.loads((h / "evidence" / "full.json").read_text())
    full["scope"] = "related"
    full["covered_tests"] = ["tests/test_x.py::test_x"]
    (h / "impact.yaml").write_text(yaml.safe_dump({"impact": {"required_tests": ["tests/test_x.py::test_x"], "full_suite": {"recommended": True}}}))
    (h / "evidence" / "full.json").write_text(json.dumps(full))
    for args in (("REPRODUCING", "--attempt", "red"), ("CONFIRMED", "--test", "tests/test_x.py::test_x", "--evidence", "red.json"), ("FIXING",), ("FIXED", "--evidence", "green.json")):
        assert cli(tmp_path, "finding", "transition", "FND-001", *args).returncode == 0
    result = cli(tmp_path, "finding", "transition", "FND-001", "VERIFIED", "--evidence", "full.json", "--critical-related-approved")
    assert result.returncode == 0, result.stderr
    finding = yaml.safe_load((h / "findings" / "fnd-001.yaml").read_text())
    assert finding["closure"]["critical_related_approved"] is True


def test_cli_preserves_finding_red_and_green_evidence_separately(tmp_path):
    h = setup(tmp_path)
    assert cli(tmp_path, "finding", "transition", "FND-001", "REPRODUCING", "--attempt", "red").returncode == 0
    red = cli(tmp_path, "evidence", "--type", "custom", "--finding", "FND-001", "--phase", "red", "--test", "tests/test_x.py::test_x", "--command", "false")
    assert red.returncode == 0, red.stderr
    red_ref = "FND-001-red-custom.json"
    assert cli(tmp_path, "finding", "transition", "FND-001", "CONFIRMED", "--test", "tests/test_x.py::test_x", "--evidence", red_ref).returncode == 0
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXING").returncode == 0
    green = cli(tmp_path, "evidence", "--type", "custom", "--finding", "FND-001", "--phase", "green", "--test", "tests/test_x.py::test_x", "--command", "true")
    assert green.returncode == 0, green.stderr
    green_ref = "FND-001-green-custom.json"
    assert cli(tmp_path, "finding", "transition", "FND-001", "FIXED", "--evidence", green_ref).returncode == 0
    assert (h / "evidence" / red_ref).is_file()
    assert (h / "evidence" / green_ref).is_file()
    assert json.loads((h / "evidence" / red_ref).read_text())["exit_code"] != 0
    assert json.loads((h / "evidence" / green_ref).read_text())["exit_code"] == 0


def test_cli_rejects_skip(tmp_path):
    h=setup(tmp_path)
    assert cli(tmp_path,"finding","transition","FND-001","VERIFIED","--evidence","full.json").returncode==1
    assert status(h)=="PROPOSED"

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


def test_cli_rejects_skip(tmp_path):
    h=setup(tmp_path)
    assert cli(tmp_path,"finding","transition","FND-001","VERIFIED","--evidence","full.json").returncode==1
    assert status(h)=="PROPOSED"

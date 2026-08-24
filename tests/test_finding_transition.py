"""TASK-004: deterministic finding lifecycle control plane."""
import json
import subprocess
import sys
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent

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
    for name,code in [("red.json",1),("green.json",0),("full.json",0)]:
      (h/"evidence"/name).write_text(json.dumps({"type":"custom","timestamp":"2026-01-01T00:00:00+00:00","command":"test","exit_code":code,"commit":head}))
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

def test_cli_rejects_skip(tmp_path):
    h=setup(tmp_path)
    assert cli(tmp_path,"finding","transition","FND-001","VERIFIED","--evidence","full.json").returncode==1
    assert status(h)=="PROPOSED"

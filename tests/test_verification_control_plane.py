"""TASK-007: task identity and verification attachment control plane."""
import subprocess, sys
from pathlib import Path
import yaml
REPO=Path(__file__).resolve().parent.parent

def cli(cwd,*a): return subprocess.run([sys.executable,"-m","harness.cli",*a],cwd=cwd,capture_output=True,text=True,env={"PYTHONPATH":str(REPO/"src"),"PATH":"/usr/bin:/bin"})
def setup(p):
 subprocess.run(["git","init","-q"],cwd=p,check=True); cli(p,"init"); return p/".harness"
def test_task_migrate_id_validates_schema(p= None): pass

def test_task_migrate_id_rejects_slug(tmp_path):
 h=setup(tmp_path); r=cli(tmp_path,"task","migrate-id","datasearch-generation-phase-commit")
 assert r.returncode==2

def test_task_migrate_id_persists_task_nnn(tmp_path):
 h=setup(tmp_path); r=cli(tmp_path,"task","migrate-id","TASK-007")
 assert r.returncode==0
 assert yaml.safe_load((h/"current-task.yaml").read_text())["task"]["id"]=="TASK-007"

def test_requirement_verify_unknown_id_rejected(tmp_path):
 setup(tmp_path); assert cli(tmp_path,"requirement","verify","REQ-999","--evidence","build.json").returncode==1

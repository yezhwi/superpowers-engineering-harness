"""TASK-008: archive completed task and create a new one."""
import subprocess,sys
from pathlib import Path
import yaml
REPO=Path(__file__).resolve().parent.parent
def cli(cwd,*a): return subprocess.run([sys.executable,'-m','harness.cli',*a],cwd=cwd,capture_output=True,text=True,env={'PYTHONPATH':str(REPO/'src'),'PATH':'/usr/bin:/bin'})
def setup(p,state='DONE'):
 subprocess.run(['git','init','-q'],cwd=p,check=True);cli(p,'init')
 subprocess.run(['git','config','user.email','test@example.com'],cwd=p,check=True);subprocess.run(['git','config','user.name','Test'],cwd=p,check=True);subprocess.run(['git','add','-A'],cwd=p,check=True);subprocess.run(['git','commit','-qm','base'],cwd=p,check=True)
 h=p/'.harness';t=yaml.safe_load((h/'current-task.yaml').read_text());t['task']['id']='TASK-001';t['task']['title']='old';t['state']=state;(h/'current-task.yaml').write_text(yaml.safe_dump(t));return h
def test_task_new_archives_done_task(tmp_path):
 h=setup(tmp_path);r=cli(tmp_path,'task','new','TASK-002','--title','next');assert r.returncode==0
 t=yaml.safe_load((h/'current-task.yaml').read_text());assert t['task']['id']=='TASK-002' and t['state']=='CREATED'
 assert any((h/'history').iterdir())
def test_task_new_resets_observability_contract(tmp_path):
 h=setup(tmp_path)
 (h/'observability.yaml').write_text('version: 1\nrequired: true\napplicability: {reasons: [old], inspected_paths: [old.py]}\nbusiness_keys: [old_id]\nfailure_boundaries: [old_boundary]\ncritical_events: [old_event]\n')
 r=cli(tmp_path,'task','new','TASK-002');assert r.returncode==0
 assert yaml.safe_load((h/'observability.yaml').read_text())['required'] is False


def test_task_new_archives_and_resets_impact(tmp_path):
 h=setup(tmp_path)
 (h/'impact.yaml').write_text('impact:\n  changed: [src/old.py]\n  direct_dependents: []\n  contracts: []\n  risks: []\n  required_tests: [tests/test_old.py]\n  full_suite: {recommended: false, reason: null}\n')
 r=cli(tmp_path,'task','new','TASK-002');assert r.returncode==0
 archive=next((h/'history').iterdir())
 assert yaml.safe_load((archive/'impact.yaml').read_text())['impact']['required_tests']==['tests/test_old.py']
 assert yaml.safe_load((h/'impact.yaml').read_text())['impact']['required_tests']==[]


def test_task_new_defaults_type_to_feature(tmp_path):
 h=setup(tmp_path)
 task=yaml.safe_load((h/'current-task.yaml').read_text())
 assert task['task']['type'] == 'feature'


def test_task_new_refuses_active_task(tmp_path):
 setup(tmp_path,'IMPLEMENTING');assert cli(tmp_path,'task','new','TASK-002').returncode==1
def test_task_new_rejects_invalid_id(tmp_path):
 setup(tmp_path);assert cli(tmp_path,'task','new','next-task').returncode==2

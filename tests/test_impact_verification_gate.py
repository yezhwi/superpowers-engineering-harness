"""TASK-010: impact plan required before VERIFYING."""
import subprocess,sys
from pathlib import Path
import yaml
REPO=Path(__file__).resolve().parent.parent
def cli(cwd,*a): return subprocess.run([sys.executable,'-m','harness.cli',*a],cwd=cwd,capture_output=True,text=True,env={'PYTHONPATH':str(REPO/'src'),'PATH':'/usr/bin:/bin'})
def setup(p):
 subprocess.run(['git','init','-q'],cwd=p,check=True);cli(p,'init');h=p/'.harness';t=yaml.safe_load((h/'current-task.yaml').read_text());t['task']['id']='TASK-010';t['state']='IMPLEMENTING';(h/'current-task.yaml').write_text(yaml.safe_dump(t));return h
def test_verifying_requires_impact_tests(tmp_path):
 setup(tmp_path);r=cli(tmp_path,'transition','VERIFYING');assert r.returncode==1
 assert 'impact.required_tests' in r.stderr

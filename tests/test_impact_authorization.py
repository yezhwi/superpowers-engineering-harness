"""TASK-010: impact full-suite recommendation requires explicit authorization."""
import subprocess,sys
from pathlib import Path
import yaml
REPO=Path(__file__).resolve().parent.parent
def cli(cwd,*a): return subprocess.run([sys.executable,'-m','harness.cli',*a],cwd=cwd,capture_output=True,text=True,env={'PYTHONPATH':str(REPO/'src'),'PATH':'/usr/bin:/bin'})
def setup(p):
 subprocess.run(['git','init','-q'],cwd=p,check=True);cli(p,'init');h=p/'.harness';t=yaml.safe_load((h/'current-task.yaml').read_text());t['task']['id']='TASK-010';t['state']='IMPLEMENTING';(h/'current-task.yaml').write_text(yaml.safe_dump(t));cli(p,'impact','add-test','tests/test_x.py::test_x');return h
def test_recommended_full_suite_blocks_verifying_without_auth(tmp_path):
 setup(tmp_path);cli(tmp_path,'impact','require-full-suite','--reason','state boundary');r=cli(tmp_path,'transition','VERIFYING');assert r.returncode==1 and 'FULL_SUITE_AUTHORIZATION_REQUIRED' in r.stderr
def test_authorized_full_suite_allows_verifying(tmp_path):
 setup(tmp_path);cli(tmp_path,'impact','require-full-suite','--reason','state boundary');cli(tmp_path,'authorize','full-suite');assert cli(tmp_path,'transition','VERIFYING').returncode==0

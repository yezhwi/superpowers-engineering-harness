"""TASK-009: explicit full-suite authorization."""
import subprocess,sys
from pathlib import Path
REPO=Path(__file__).resolve().parent.parent
def cli(cwd,*a): return subprocess.run([sys.executable,'-m','harness.cli',*a],cwd=cwd,capture_output=True,text=True,env={'PYTHONPATH':str(REPO/'src'),'PATH':'/usr/bin:/bin'})
def setup(p):
 subprocess.run(['git','init','-q'],cwd=p,check=True);cli(p,'init')
 subprocess.run(['git','add','-A'],cwd=p,check=True);subprocess.run(['git','commit','-qm','init'],cwd=p,check=True)
def test_full_suite_rejected_without_authorization(tmp_path):
 setup(tmp_path);r=cli(tmp_path,'evidence','--type','unit_test','--scope','full_suite','--command','false');assert r.returncode==2
def test_authorization_allows_full_suite(tmp_path):
 setup(tmp_path);assert cli(tmp_path,'authorize','full-suite').returncode==0
 assert cli(tmp_path,'evidence','--type','unit_test','--scope','full_suite','--command','true').returncode==0

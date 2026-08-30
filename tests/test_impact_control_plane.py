"""TASK-010: persisted impact analysis control plane."""
import subprocess,sys
from pathlib import Path
import yaml
REPO=Path(__file__).resolve().parent.parent
def cli(cwd,*a): return subprocess.run([sys.executable,'-m','harness.cli',*a],cwd=cwd,capture_output=True,text=True,env={'PYTHONPATH':str(REPO/'src'),'PATH':'/usr/bin:/bin'})
def setup(p): subprocess.run(['git','init','-q'],cwd=p,check=True);cli(p,'init')
def test_impact_requires_action_and_does_not_write(tmp_path):
 setup(tmp_path)
 path=tmp_path/'.harness/impact.yaml'
 before=path.read_bytes()
 result=cli(tmp_path,'impact')
 assert result.returncode==2
 assert path.read_bytes()==before

def test_impact_add_change_and_test(tmp_path):
 setup(tmp_path);assert cli(tmp_path,'impact','add-change','src/x.py').returncode==0
 assert cli(tmp_path,'impact','add-test','tests/test_x.py::test_x').returncode==0
 d=yaml.safe_load((tmp_path/'.harness/impact.yaml').read_text());assert d['impact']['changed']==['src/x.py'] and d['impact']['required_tests']
def test_impact_require_full_suite_records_reason(tmp_path):
 setup(tmp_path);assert cli(tmp_path,'impact','require-full-suite','--reason','state boundary').returncode==0
 assert 'state boundary' in cli(tmp_path,'impact','show').stdout

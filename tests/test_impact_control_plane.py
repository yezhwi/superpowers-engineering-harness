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
 assert yaml.safe_load((tmp_path/'.harness/current-task.yaml').read_text())['scope']['owned_paths']==['src/x.py']
def test_scope_migrates_legacy_impact_changed_without_adopting_workspace(tmp_path):
 setup(tmp_path)
 assert cli(tmp_path,'impact','add-change','src/legacy.py').returncode==0
 task=yaml.safe_load((tmp_path/'.harness/current-task.yaml').read_text()); task.pop('scope',None); (tmp_path/'.harness/current-task.yaml').write_text(yaml.safe_dump(task))
 assert cli(tmp_path,'impact','scope','--format','yaml').returncode==0
 assert yaml.safe_load((tmp_path/'.harness/current-task.yaml').read_text())['scope']['owned_paths']==['src/legacy.py']

def test_impact_adopted_path_enters_scope_but_protected_path_does_not(tmp_path):
 setup(tmp_path)
 task=yaml.safe_load((tmp_path/'.harness/current-task.yaml').read_text())
 task['scope']={'owned_paths':[],'protected_user_paths':['docs/user.md']}
 (tmp_path/'.harness/current-task.yaml').write_text(yaml.safe_dump(task))
 assert cli(tmp_path,'impact','adopt-path','src/x.py').returncode==0
 result=cli(tmp_path,'impact','scope','--format','yaml')
 assert result.returncode==0
 scope=yaml.safe_load(result.stdout)
 assert scope['owned_paths']==['src/x.py']
 assert 'docs/user.md' not in scope['effective_scope']

def test_impact_require_full_suite_records_reason(tmp_path):
 setup(tmp_path);assert cli(tmp_path,'impact','require-full-suite','--reason','state boundary').returncode==0
 assert 'state boundary' in cli(tmp_path,'impact','show').stdout


def test_q1_external_interface_requires_explicit_escalation(tmp_path):
 setup(tmp_path)
 subprocess.run(['git','config','user.email','test@example.com'],cwd=tmp_path,check=True); subprocess.run(['git','config','user.name','Test'],cwd=tmp_path,check=True); subprocess.run(['git','add','.'],cwd=tmp_path,check=True); subprocess.run(['git','commit','-qm','base'],cwd=tmp_path,check=True)
 flags=[item for pair in {'scope':'low','contract':'none','data':'none','authorization':'none','security':'none','concurrency':'none','deployment':'none'}.items() for item in (f'--{pair[0]}',pair[1])]
 assert cli(tmp_path,'task','classify','--level','Q1',*flags).returncode==0
 result=cli(tmp_path,'impact','add-interface','INT-001','--kind','cli','--consumer','agent','--compatibility','compatible')
 assert result.returncode==1
 assert 'PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED' in result.stderr


def test_ignore_user_path_revokes_existing_ownership(tmp_path):
 setup(tmp_path)
 assert cli(tmp_path, 'impact', 'add-change', 'src/x.py').returncode == 0
 assert cli(tmp_path, 'impact', 'ignore-user-path', 'src/x.py').returncode == 0
 scope=yaml.safe_load(cli(tmp_path, 'impact', 'scope', '--format', 'yaml').stdout)
 assert 'src/x.py' not in scope['owned_paths']
 assert 'src/x.py' not in scope['effective_scope']


def test_project_task_scope_includes_inspected_paths_and_excludes_protected_paths():
 from harness.workspace import project_task_scope
 task={'scope': {'owned_paths': ['src/owned.py'], 'protected_user_paths': ['docs/user.md']}}
 impact={'contracts': ['src/contract.py'], 'direct_dependents': ['src/dependent.py']}
 assert project_task_scope(task, impact, inspected_paths=['src/inspected.py']) == (
  'src/contract.py', 'src/dependent.py', 'src/inspected.py', 'src/owned.py')

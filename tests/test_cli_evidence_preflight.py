"""Public v2 parser/repository/JSON boundary; v1 and Gate remain unchanged."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_context_builder as fixtures

from harness import cli, controlplane, quality_gate

harness = fixtures.harness
REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('arguments', [
    ['--preflight'], ['--command','pytest x.py'], ['--skills-package','/tmp/package.json'],
    ['--probe-launcher','/tmp/harness'], ['--preflight','--json','--command',''],
    ['--preflight','--json','--command','  '], ['--preflight','--json','--skills-package','relative/package.json'],
    ['--preflight','--json','--probe-launcher','relative/harness'],
    ['--preflight','--json','--probe-launcher','/a','--probe-launcher','/b'],
    ['--preflight','--json','--skills-package','/a','--skills-package','/b'],
    ['--preflight','--json','--command'], ['--preflight','--json','--unknown'],
    ['--preflight','--json','--probe-launcher','/a\x00b'],
])
def test_invalid_arguments_refuse_before_repository_or_execution(tmp_path, monkeypatch, capsys, arguments):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, 'find_git_root', lambda *a: pytest.fail('repository lookup before argument validation'))
    with pytest.raises(SystemExit) as caught:
        cli.main(['evidence','plan',*arguments])
    captured = capsys.readouterr()
    assert caught.value.code == 2
    assert captured.out == ''
    assert 'error:' in captured.err


def invoke(root, *arguments):
    return subprocess.run([sys.executable,'-m','harness.cli','evidence','plan',*arguments], cwd=root,
                          env={**os.environ,'PYTHONPATH':str(REPO/'src')},
                          capture_output=True,text=True,check=False,timeout=30)


def test_non_git_stays_stderr_only_without_probe(tmp_path):
    marker = tmp_path / 'marker'
    launcher = tmp_path / 'launcher'
    launcher.write_text(f'#!{sys.executable}\nfrom pathlib import Path; Path({str(marker)!r}).touch()\n')
    launcher.chmod(0o755)
    result = invoke(tmp_path,'--preflight','--json','--probe-launcher',str(launcher))
    assert result.returncode == 1
    assert result.stdout == ''
    assert result.stderr.startswith('ERROR:')
    assert not marker.exists()


def test_in_repo_missing_sources_retains_probe_and_original_cwd(tmp_path):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    nested = tmp_path / 'nested'
    nested.mkdir()
    marker = tmp_path / 'cwd.json'
    launcher = tmp_path / 'launcher'
    launcher.write_text(f'#!{sys.executable}\nimport os,json\nfrom pathlib import Path\nPath({str(marker)!r}).write_text(json.dumps(os.getcwd()))\n')
    launcher.chmod(0o755)
    result = invoke(nested,'--preflight','--json','--probe-launcher',str(launcher))
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report['exit_code'] == 2
    assert report['integrity']['status'] == 'INVALID'
    assert report['tooling']['launcher_probe']['status'] == 'SUCCEEDED'
    assert report['execution_counts'] == {'tests':0,'business':0,'environment':1}
    assert json.loads(marker.read_text()) == str(nested)
    assert result.stderr == ''


def test_repeated_boolean_flags_and_commands_keep_literal_order(harness, capsys):
    result = cli.main(['evidence','plan','--preflight','--preflight','--json','--json',
                      '--command','pytest a.py','--command','pytest b.py','--command','pytest a.py'])
    report = json.loads(capsys.readouterr().out)
    assert result == report['exit_code'] == 1
    assert [row['command'] for row in report['execution_capabilities']['commands']] == ['pytest a.py','pytest b.py']
    assert report['version'] == 2


def test_v1_keeps_old_json_and_success_with_product_gaps(harness, capsys):
    result = cli.main(['evidence','plan','--json'])
    report = json.loads(capsys.readouterr().out)
    assert result == 0
    assert report['version'] == 1
    assert 'integrity' not in report
    assert report['execution_counts'] == {'tests':0,'business':0,'environment':0}


def test_probe_help_explicitly_warns_unsandboxed_execution(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(['evidence','plan','--help'])
    assert caught.value.code == 0
    assert 'unsandboxed' in capsys.readouterr().out


def test_gate_preflight_existing_stdout_stays_unchanged(harness, monkeypatch, capsys):
    assessment = SimpleNamespace(status='PASS',release_readiness={'status':'READY'},blockers=(),plan_assessment=None)
    monkeypatch.setattr(quality_gate,'assess_gate',lambda *a,**k:assessment)
    assert controlplane.cmd_gate_preflight() == 0
    assert capsys.readouterr().out == 'READY: yes\n'

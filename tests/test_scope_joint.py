"""Gate, stage entry and CLI add activate through same scope mechanism."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml
from test_context_builder import write_yaml
from test_test_scope import SCOPE_FILES, initialize_test_origin, scope_codes, tree_bytes

from harness.blockers import GateBlocker, is_user_authority_blocker, select_recovery

harness = test_context_builder.harness
REPO = Path(__file__).resolve().parents[1]


def cli(root, *args):
    return subprocess.run([sys.executable, '-m', 'harness.cli', *args], cwd=root.parent,
                          env={**os.environ, 'PYTHONPATH': str(REPO / 'src')}, capture_output=True,
                          text=True, check=False, timeout=40)


def test_cli_add_then_hand_delete_cannot_disappear_from_scope(harness):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    result = cli(harness, 'impact', 'add-test', 'test_b.py')
    assert result.returncode == 0, result.stderr
    audit = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    assert [event['operation'] for event in audit['entries']] == ['ADD']
    before = tree_bytes(harness)
    assert cli(harness, 'impact', 'add-test', 'test_b.py').returncode == 0
    assert tree_bytes(harness) == before
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': ['test_a.py']}})
    assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUDITED'}


def test_verify_stage_rejects_unaudited_shrink_before_state_write(harness):
    initialize_test_origin(harness, ['test_a.py'])
    task = yaml.safe_load((harness / 'current-task.yaml').read_text())
    task['state'] = 'IMPLEMENTING'
    write_yaml(harness / 'current-task.yaml', task)
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': []}})
    before = tree_bytes(harness)
    result = cli(harness, 'transition', 'VERIFYING')
    assert result.returncode != 0
    assert 'TEST_SCOPE_RETIREMENT_UNAUDITED' in result.stdout + result.stderr
    assert tree_bytes(harness) == before


@pytest.mark.parametrize('code', ['TEST_SCOPE_AUDIT_INVALID', 'TEST_SCOPE_RETIREMENT_UNAUDITED', 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'])
def test_scope_blockers_cannot_autonomously_resume(code):
    assert is_user_authority_blocker(code)
    assert select_recovery([GateBlocker(code, 'harness', code)]) is None


def test_cold_context_loads_scope_evaluator_before_read_authority_freezes(harness):
    initialize_test_origin(harness, ['test_a.py'])
    import shutil

    # Harness self-hosting: evaluator's Python source also lives beneath read root.
    shutil.copytree(REPO / 'src', harness.parent / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    result = subprocess.run([sys.executable, '-m', 'harness.cli', 'context', '--compact'], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(harness.parent / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True,
                            text=True, check=False, timeout=40)
    assert result.returncode == 0, result.stderr
    assert 'TEST_SCOPE_AUDIT_INVALID' not in result.stdout


def test_cli_add_missing_origin_does_not_initialize_task_scope(harness):
    for name in SCOPE_FILES:
        (harness / name).unlink()
    task = yaml.safe_load((harness / 'current-task.yaml').read_text())
    task.pop('scope', None)
    write_yaml(harness / 'current-task.yaml', task)
    (harness.parent / 'test_a.py').write_text('def test_ok():\n    pass\n')
    before = tree_bytes(harness)
    result = cli(harness, 'impact', 'add-test', 'test_a.py')
    assert result.returncode != 0
    assert 'TEST_SCOPE_AUDIT_INVALID' in result.stdout + result.stderr
    assert tree_bytes(harness) == before

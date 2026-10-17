"""Explicit CLI reconstructs selected scope only, never retires or resumes."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml
from test_scope_migration import historical_preparation, preparation
from test_test_scope import SCOPE_FILES, tree_bytes

harness = test_context_builder.harness
REPO = Path(__file__).resolve().parents[1]


def invoke(root, request):
    proposal = root.parent / 'migration.yaml'
    proposal.write_text(yaml.safe_dump(request))
    return subprocess.run([sys.executable, '-m', 'harness.cli', 'impact', 'migrate-scope', '--file', str(proposal)],
                          cwd=root.parent, env={**os.environ, 'PYTHONPATH': str(REPO / 'src')},
                          capture_output=True, text=True, timeout=40, check=False)


@pytest.mark.parametrize('history', [False, True])
def test_cli_reconstructs_original_and_reports_remaining_blocker(harness, history):
    request, original = historical_preparation(harness) if history else preparation(harness)
    before = tree_bytes(harness)
    result = invoke(harness, request)
    assert result.returncode == 0, result.stderr
    report = yaml.safe_load(result.stdout)
    assert report['status'] == 'BLOCKED'
    assert report['diagnostics'] == [{'code': 'TEST_SCOPE_RETIREMENT_UNAUDITED'}]
    assert report['context_regeneration_required'] is True
    assert yaml.safe_load((harness / SCOPE_FILES[0]).read_text())['required_tests'] == original
    for name, data in before.items():
        if name != 'gate.yaml':
            assert (harness / name).read_bytes() == data


def test_cli_wrong_task_rejects_without_initializing_or_task_scope_write(harness):
    request, _ = preparation(harness)
    request['task_id'] = 'TASK-999'
    before = tree_bytes(harness)
    result = invoke(harness, request)
    assert result.returncode == 2
    assert 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED' in result.stderr
    assert tree_bytes(harness) == before

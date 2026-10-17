"""Actual creation publication binds initial scope, not an assumed empty set."""

import shutil

import pytest
import test_context_builder
import yaml
from test_context_builder import write_yaml
from test_test_scope import SCOPE_FILES, initialize_test_origin

from harness import controlplane
from harness.templates import templates_dir

harness = test_context_builder.harness


@pytest.mark.parametrize('initial', [[], ['test_initial.py']])
@pytest.mark.parametrize('route', ['new', 'recover'])
def test_replacement_publishes_task_bound_actual_template_scope(harness, tmp_path, monkeypatch, initial, route):
    initialize_test_origin(harness, ['test_old.py'])
    task = yaml.safe_load((harness / 'current-task.yaml').read_text())
    task['state'] = 'DONE' if route == 'new' else 'CLASSIFIED'
    write_yaml(harness / 'current-task.yaml', task)
    custom = tmp_path.parent / f'{tmp_path.name}-templates'
    shutil.copytree(templates_dir(), custom)
    write_yaml(custom / 'impact.yaml', {'impact': {'changed': [], 'required_tests': initial}})
    if initial:
        (harness.parent / initial[0]).write_text('def test_ok():\n    pass\n')
    monkeypatch.setattr(controlplane, 'templates_dir', lambda: custom)
    if route == 'new':
        assert controlplane.cmd_task_new('TASK-777', 'replacement origin') == 0
    else:
        assert controlplane.cmd_task_recover('TASK-777', 'replacement origin', 'explicit test recovery') == 0
    baseline = yaml.safe_load((harness / SCOPE_FILES[0]).read_text())
    assert baseline['task_id'] == 'TASK-777'
    assert baseline['required_tests'] == initial
    archives = list((harness / 'history').glob('TASK-028-*'))
    assert len(archives) == 1
    assert all((archives[0] / name).is_file() for name in SCOPE_FILES)
    archived = yaml.safe_load((archives[0] / SCOPE_FILES[0]).read_text())
    assert archived['required_tests'] == ['test_old.py']

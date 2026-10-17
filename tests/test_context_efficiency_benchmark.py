"""Anonymous benchmark inputs and reports are reproducible, not speedup assertions."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def runner():
    path = REPO / 'benchmarks/context_efficiency.py'
    assert path.is_file(), 'independent archived-reference benchmark runner missing'
    spec = importlib.util.spec_from_file_location('context_efficiency_benchmark', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_anonymous_fixture_is_byte_identical_for_same_seed_and_count(tmp_path):
    module = runner()
    one, two = tmp_path / 'one', tmp_path / 'two'
    module.make_fixture(one, REPO / 'src/harness/templates', seed=1038001, count=1)
    module.make_fixture(two, REPO / 'src/harness/templates', seed=1038001, count=1)
    inventory = lambda root: {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / '.harness').rglob('*') if p.is_file()}
    assert inventory(one) == inventory(two)
    task = json.loads(module.fixture_identity(one))
    assert task['finding_count'] == 1
    assert module.fixture_identity(one) == module.fixture_identity(two)


def test_summary_never_counts_failed_or_timeout_runs_as_success():
    module = runner()
    report = module.summarize([{'status': 'SUCCESS', 'wall_ms': 10}, {'status': 'SUCCESS', 'wall_ms': 30},
                               {'status': 'TIMEOUT', 'wall_ms': 1}, {'status': 'FAILED', 'wall_ms': 2}])
    assert report == {'successful': 2, 'failed': 2, 'min_ms': 10, 'median_ms': 20, 'max_ms': 30}


def test_semantic_comparison_normalizes_only_declared_legacy_blocker_and_root():
    module = runner()
    blocker = {'code': 'TEST_SCOPE_AUDIT_INVALID'}
    retained = {'code': 'SCOPE_DRIFT_PERMISSION'}
    document = {'control': {'gate': {'blocked_by': [blocker, retained]}, 'blockers': [blocker, retained]},
                'working': {}, 'omitted': [], 'references': {}, 'policy': 'LOCAL', 'expansions': []}
    facts = module.semantics(document)
    assert facts['control']['blockers'] == [retained]
    assert facts['control']['gate']['blocked_by'] == [retained]
    assert module.normalized(str(Path.cwd()) + '/.harness/test.yaml') == '<fixture>/.harness/test.yaml'


def test_report_output_must_be_outside_repository():
    module = runner()
    with pytest.raises(ValueError):
        module.check_output(REPO / 'benchmark-report.json', REPO)

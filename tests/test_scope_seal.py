"""Alignment v3 freezes immutable scope origin, never mutable audit head."""

import importlib

import test_context_builder
import yaml
from test_context_builder import _frozen_alignment, write_yaml
from test_test_scope import SCOPE_FILES, initialize_test_origin

from harness import alignment
from harness.context.freshness import capture
from harness.schema_resources import read_schema

harness = test_context_builder.harness
BOUNDARIES = {'interface': [], 'permission': [], 'persistence': []}
FACTS = alignment.ArchitectureFreezeFacts('off', None, ())


def freeze_scope(root):
    scope = importlib.import_module('harness._scope_replay')
    assert hasattr(scope, 'freeze_scope_facts'), 'immutable scope freeze projection missing'
    document = _frozen_alignment('TASK-028')
    write_yaml(root / 'alignment.yaml', document)
    record = alignment.freeze_record(document, decisions=[], boundary_refs=BOUNDARIES,
                                     architecture_mode='off', architecture_fingerprint=None, declared_modules=(),
                                     test_scope=scope.freeze_scope_facts(root))
    write_yaml(root / 'alignment-freeze.yaml', record)
    return document, record


def test_v3_scope_freeze_schema_and_immutable_projection(harness):
    initialize_test_origin(harness, ['test_a.py'])
    _, record = freeze_scope(harness)
    from jsonschema import validate
    validate(record, read_schema('alignment-freeze.schema.json'))
    assert record['version'] == 3
    assert set(record['test_scope']) == {'baseline_hash', 'origin_decisions'}


def test_baseline_and_scope_seal_rewrite_cannot_evade_existing_v3_guard(harness):
    initialize_test_origin(harness, ['test_a.py'])
    document, _ = freeze_scope(harness)
    scope = importlib.import_module('harness._scope_replay')
    baseline = yaml.safe_load((harness / SCOPE_FILES[0]).read_text())
    baseline['source_hashes']['impact.yaml'] = 'sha256:' + '0' * 64
    write_yaml(harness / SCOPE_FILES[0], baseline)
    seal = yaml.safe_load((harness / SCOPE_FILES[2]).read_text())
    seal['baseline_hash'] = scope.raw_hash((harness / SCOPE_FILES[0]).read_bytes())
    seal['audit_head'] = seal['baseline_hash']
    write_yaml(harness / SCOPE_FILES[2], seal)
    issues = alignment.sealed_freeze_drift(harness, document, decisions=[], boundary_refs=BOUNDARIES,
                                          bootstrap_legacy_off=False, architecture_facts=FACTS)
    assert [issue.code for issue in issues] == ['CONTRACT_CHANGED']


def test_formal_add_does_not_change_frozen_origin_projection(harness):
    initialize_test_origin(harness, ['test_a.py'])
    document, _ = freeze_scope(harness)
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    importlib.import_module('harness.test_scope').add_required_test(harness, 'test_b.py')
    assert alignment.sealed_freeze_drift(harness, document, decisions=[], boundary_refs=BOUNDARIES,
                                        bootstrap_legacy_off=False, architecture_facts=FACTS) == []


def test_scope_sources_enrolled_in_capture(harness):
    initialize_test_origin(harness, ['test_a.py'])
    before = capture(harness)
    assert all(name in before['files'] for name in SCOPE_FILES)
    (harness / SCOPE_FILES[1]).write_bytes((harness / SCOPE_FILES[1]).read_bytes() + b'\n')
    after = capture(harness)
    assert after != before


def test_fast_bootstrap_seals_existing_trusted_origin_as_v3(harness):
    initialize_test_origin(harness, ['test_a.py'])
    document = _frozen_alignment('TASK-028')
    write_yaml(harness / 'alignment.yaml', document)
    assert alignment.sealed_freeze_drift(harness, document, decisions=[], boundary_refs=BOUNDARIES,
                                        bootstrap_legacy_off=True, architecture_facts=FACTS) == []
    record = yaml.safe_load((harness / 'alignment-freeze.yaml').read_text())
    assert record['version'] == 3
    assert 'test_scope' in record


def test_legacy_seal_freeze_projection_does_not_create_origin(harness):
    scope = importlib.import_module('harness._scope_replay')
    assert hasattr(scope, 'freeze_scope_facts'), 'immutable scope freeze projection missing'
    for name in SCOPE_FILES:
        (harness / name).unlink(missing_ok=True)
    assert scope.freeze_scope_facts(harness) is None
    assert not any((harness / name).exists() for name in SCOPE_FILES)

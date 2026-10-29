"""PF-19/20: retain native drift payload without changing old consumers."""
from types import SimpleNamespace

import pytest
import test_context_builder as fixtures

from harness import alignment, quality_gate
from harness.context.model import ContextBuildError
from harness.context.source import FileContextSource

harness = fixtures.harness


def test_two_argument_error_preserves_code_and_text():
    error = ContextBuildError('CONTEXT_SCHEMA_INVALID', 'alignment sealed mismatch: CONTRACT_CHANGED')
    assert error.code == 'CONTEXT_SCHEMA_INVALID'
    assert str(error) == 'CONTEXT_SCHEMA_INVALID: alignment sealed mismatch: CONTRACT_CHANGED'
    assert error.drift_codes is None


def test_keyword_payload_preserves_type_code_and_text():
    error = ContextBuildError('CONTEXT_SCHEMA_INVALID', 'original detail',
                              drift_codes=('SCOPE_DRIFT_API', 'SCOPE_DRIFT_PERMISSION'))
    assert isinstance(error, ValueError)
    assert error.code == 'CONTEXT_SCHEMA_INVALID'
    assert str(error) == 'CONTEXT_SCHEMA_INVALID: original detail'
    assert error.drift_codes == ('SCOPE_DRIFT_API', 'SCOPE_DRIFT_PERMISSION')


def _unreachable(*args, **kwargs):
    pytest.fail('loader continued past original drift throw site')


def test_contract_hash_failure_keeps_early_throw_and_payload(harness, monkeypatch):
    document = fixtures._frozen_alignment()
    document['freeze']['contract_hash'] = 'sha256:' + '0' * 64
    fixtures.write_yaml(harness / 'alignment.yaml', document)
    monkeypatch.setattr(alignment, 'sealed_freeze_drift', _unreachable)
    monkeypatch.setattr(quality_gate, 'assess_gate', _unreachable)
    from harness import _scope_replay
    monkeypatch.setattr(_scope_replay, 'assess_test_scope_retirements', _unreachable)
    with pytest.raises(ContextBuildError) as caught:
        FileContextSource(harness).load()
    assert caught.value.code == 'CONTEXT_SCHEMA_INVALID'
    assert str(caught.value) == 'CONTEXT_SCHEMA_INVALID: alignment sealed mismatch: CONTRACT_CHANGED'
    assert caught.value.drift_codes == ('CONTRACT_CHANGED',)


def test_seal_failure_keeps_every_available_drift_code(harness, monkeypatch):
    document = fixtures._frozen_alignment()
    fixtures.write_yaml(harness / 'alignment.yaml', document)
    fixtures._write_matching_seal(harness, document)
    codes = ('SCOPE_DRIFT_API', 'SCOPE_DRIFT_PERMISSION', 'SCOPE_DRIFT_PERSISTENCE', 'SCOPE_DRIFT_API')
    calls = []
    def drift(*args, **kwargs):
        calls.append('seal')
        return [SimpleNamespace(code=code) for code in codes]
    monkeypatch.setattr(alignment, 'sealed_freeze_drift', drift)
    monkeypatch.setattr(quality_gate, 'assess_gate', _unreachable)
    from harness import _scope_replay
    monkeypatch.setattr(_scope_replay, 'assess_test_scope_retirements', _unreachable)
    with pytest.raises(ContextBuildError) as caught:
        FileContextSource(harness).load()
    assert calls == ['seal']
    assert caught.value.code == 'CONTEXT_SCHEMA_INVALID'
    assert str(caught.value) == 'CONTEXT_SCHEMA_INVALID: alignment sealed mismatch: SCOPE_DRIFT_API'
    assert caught.value.drift_codes == codes

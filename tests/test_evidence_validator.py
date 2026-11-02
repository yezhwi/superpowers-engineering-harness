"""Shared Evidence freshness and regression-identity validation."""

import sys
from pathlib import Path

import pytest
from evidence_factory import synthetic_execution

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from evidence_validator import (
    EvidenceValidationError,
    validate_evidence,
    validate_finding_closure_evidence,
    ReuseRequest,
    can_reuse_evidence,
)

HEAD = "a" * 40
FP = "sha256:" + "b" * 64
TEST = "tests/test_refund.py::test_double_refund"


def record(**changes):
    base = {
        "type": "custom",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "command": f"pytest {TEST}",
        "exit_code": 1,
        "commit": HEAD,
        "workspace_fingerprint": FP,
        "workspace_fingerprint_after": FP,
        "subject": {"kind": "finding", "id": "FND-001"},
        "test": {"node_id": TEST},
    }
    value = {**base, **changes}
    value["test_execution"] = synthetic_execution([TEST, *value.get("covered_tests", [])], value["exit_code"])
    return value


RUNTIME = {
    "implementation": "CPython",
    "version": "3.11.10",
    "executable": "/python",
    "platform": "Linux-x86_64",
}


def generic_record(**changes):
    evidence = record(
        type="unit_test",
        command=f"pytest {TEST}",
        exit_code=0,
        scope="related",
        covered_tests=[TEST],
        runtime=RUNTIME,
    )
    evidence.pop("subject")
    evidence.pop("test")
    evidence = {**evidence, **changes}
    evidence["test_execution"] = synthetic_execution(evidence.get("covered_tests"), evidence["exit_code"])
    return evidence


def test_batch_major_requires_each_real_execution_before_coverage_union():
    from harness.evidence_validator import validate_finding_closure_batch
    records = [generic_record(covered_tests=['tests/a.py']), generic_record(covered_tests=['tests/b.py'])]
    validate_finding_closure_batch({'severity': 'major'}, records,
        {'impact': {'required_tests': ['tests/a.py', 'tests/b.py']}}, current_head=HEAD, current_workspace=FP)


@pytest.mark.parametrize('damage', ['missing-scope', 'full-scope', 'custom', 'failed', 'missing-execution', 'stale', 'uncovered', 'empty-required'])
def test_batch_rejects_any_bad_member_or_missing_current_required_set(damage):
    from harness.evidence_validator import validate_finding_closure_batch
    records = [generic_record(covered_tests=['tests/a.py']), generic_record(covered_tests=['tests/b.py'])]
    required = ['tests/a.py', 'tests/b.py']
    if damage == 'missing-scope':
        records[1].pop('scope')
    elif damage == 'full-scope':
        records[1]['scope'] = 'full'
    elif damage == 'custom':
        records[1]['type'] = 'custom'
    elif damage == 'failed':
        records[1]['exit_code'] = 1
    elif damage == 'missing-execution':
        records[1].pop('test_execution')
    elif damage == 'stale':
        records[1]['workspace_fingerprint'] = 'sha256:' + '0' * 64
    elif damage == 'uncovered':
        required.append('tests/c.py')
    else:
        required = []
    with pytest.raises(EvidenceValidationError):
        validate_finding_closure_batch({'severity': 'major'}, records, {'impact': {'required_tests': required}},
                                      current_head=HEAD, current_workspace=FP)


@pytest.mark.parametrize('approved', [False, True])
def test_batch_critical_requires_finding_approval_only(approved):
    from harness.evidence_validator import validate_finding_closure_batch
    finding = {'severity': 'critical'}
    if approved:
        finding['closure'] = {'mode': 'related', 'source': 'user', 'approved_at': '2000-01-01', 'critical_related_approved': True}
    records = [generic_record(covered_tests=['tests/a.py']), generic_record(covered_tests=['tests/b.py'])]
    kwargs = {'current_head': HEAD, 'current_workspace': FP}
    if approved:
        validate_finding_closure_batch(finding, records, {'impact': {'required_tests': ['tests/a.py', 'tests/b.py']}}, **kwargs)
    else:
        with pytest.raises(EvidenceValidationError, match='CRITICAL_RELATED_APPROVAL_REQUIRED'):
            validate_finding_closure_batch(finding, records, {'impact': {'required_tests': ['tests/a.py', 'tests/b.py']}}, **kwargs)


def reuse_request():
    return ReuseRequest(
        "unit_test", f"pytest {TEST}", "related", (TEST,), None, None, None
    )


@pytest.mark.parametrize("phase, evidence_phase, changes, expected", [
    ("green", "green", {}, True), ("green", None, {}, False),
    ("green", "red", {}, False), (None, "green", {}, False),
    ("red", "red", {}, False), ("red", "red", {"exit_code": 1}, False),
    ("full", "full", {}, False),
    ("green", "green", {"exit_code": 1}, False),
    ("green", "green", {"subject": {"kind": "finding", "id": "FND-001"}}, False),
    ("green", "green", {"command": "pytest other"}, False),
    ("green", "green", {"covered_tests": []}, False),
    ("green", "green", {"workspace_fingerprint_after": "sha256:" + "0" * 64}, False),
    ("green", "green", {"runtime": {}}, False),
])
def test_reuse_requires_exact_task_phase(phase, evidence_phase, changes, expected):
    evidence = generic_record(**changes)
    if evidence_phase is not None:
        evidence["phase"] = evidence_phase
    request = ReuseRequest("unit_test", f"pytest {TEST}", "related", (TEST,), phase, None, None)
    assert can_reuse_evidence(
        evidence, request, current_head=HEAD, current_workspace=FP, current_runtime=RUNTIME
    ) is expected


@pytest.mark.parametrize("evidence_type", ["unit_test", "integration_test", "contract_test"])
@pytest.mark.parametrize("changes, expected", [
    ({}, True), ({"covered_tests": ["tests/other.py"]}, False),
    ({"scope": None}, False), ({"scope": "full"}, False),
])
def test_green_reuse_matches_test_coverage_for_all_test_types(evidence_type, changes, expected):
    request = ReuseRequest(evidence_type, f"pytest {TEST}", "related", (TEST,), "green", None, None)
    assert can_reuse_evidence(
        generic_record(type=evidence_type, phase="green", **changes),
        request, current_head=HEAD, current_workspace=FP, current_runtime=RUNTIME,
    ) is expected


@pytest.mark.parametrize("field", ["covered_tests", "covered_test_cases"])
@pytest.mark.parametrize("value", [None, [{}], "not a list"])
def test_reuse_malformed_coverage_returns_false_without_exception(field, value):
    evidence = generic_record()
    evidence[field] = value
    assert can_reuse_evidence(evidence, reuse_request(), current_head=HEAD,
                             current_workspace=FP, current_runtime=RUNTIME) is False


def test_reuse_requires_exact_generic_successful_evidence():
    evidence = generic_record()
    assert can_reuse_evidence(
        evidence,
        reuse_request(),
        current_head=HEAD,
        current_workspace=FP,
        current_runtime=RUNTIME,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"command": "pytest other"},
        {"exit_code": 1},
        {"workspace_fingerprint_after": "sha256:" + "0" * 64},
        {"runtime": {}},
        {"subject": {"kind": "finding", "id": "FND-001"}},
    ],
)
def test_reuse_rejects_nonidentical_or_non_generic_proof(changes):
    evidence = generic_record(**changes)
    assert not can_reuse_evidence(
        evidence,
        reuse_request(),
        current_head=HEAD,
        current_workspace=FP,
        current_runtime=RUNTIME,
    )


@pytest.mark.parametrize('attack', ['head', 'before_workspace', 'after_workspace', 'command', 'scope', 'tests',
                                  'cases', 'runtime', 'schema', 'subject', 'test', 'request_finding', 'request_test'])
def test_exact_reuse_predicate_rejects_each_identity_mismatch(attack):
    from dataclasses import replace

    evidence = generic_record(phase='green', covered_test_cases=['TC-001'])
    request = ReuseRequest('unit_test', f'pytest {TEST}', 'related', (TEST,), 'green', None, None, ('TC-001',))
    if attack == 'head':
        evidence['commit'] = 'c' * 40
    elif attack == 'before_workspace':
        evidence['workspace_fingerprint'] = 'sha256:' + '0' * 64
    elif attack == 'after_workspace':
        evidence['workspace_fingerprint_after'] = 'sha256:' + '0' * 64
    elif attack == 'command':
        evidence['command'] = 'pytest other.py'
    elif attack == 'scope':
        evidence['scope'] = 'full'
    elif attack == 'tests':
        evidence['covered_tests'] = []
    elif attack == 'cases':
        evidence['covered_test_cases'] = []
    elif attack == 'runtime':
        evidence['runtime'] = {**RUNTIME, 'version': 'different'}
    elif attack == 'schema':
        evidence.pop('timestamp')
    elif attack == 'subject':
        evidence['subject'] = {'kind': 'finding', 'id': 'FND-001'}
    elif attack == 'test':
        evidence['test'] = {'node_id': TEST}
    elif attack == 'request_finding':
        request = replace(request, finding_id='FND-001')
    else:
        request = replace(request, test_id=TEST)
    assert not can_reuse_evidence(evidence, request, current_head=HEAD, current_workspace=FP, current_runtime=RUNTIME)


def test_exact_reuse_accepts_set_equal_coverages_not_subset():
    evidence = generic_record(phase='green', covered_tests=[TEST, 'tests/other.py'], covered_test_cases=['TC-001', 'TC-002'])
    request = ReuseRequest('unit_test', f'pytest {TEST}', 'related', ('tests/other.py', TEST), 'green', None, None, ('TC-002', 'TC-001'))
    assert can_reuse_evidence(evidence, request, current_head=HEAD, current_workspace=FP, current_runtime=RUNTIME)


def test_rejects_workspace_stale_evidence():
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_WORKSPACE_STALE"):
        validate_evidence(
            record(), current_head=HEAD, current_workspace="sha256:" + "c" * 64
        )


def test_rejects_wrong_finding_subject():
    with pytest.raises(EvidenceValidationError, match="FINDING_SUBJECT_MISMATCH"):
        validate_evidence(
            record(subject={"kind": "finding", "id": "FND-002"}),
            current_head=HEAD,
            current_workspace=FP,
            finding_id="FND-001",
            test_id=TEST,
        )


def test_rejects_unrelated_test_identity():
    with pytest.raises(EvidenceValidationError, match="REGRESSION_TEST_MISMATCH"):
        validate_evidence(
            record(test={"node_id": "tests/test_other.py::test_other"}),
            current_head=HEAD,
            current_workspace=FP,
            finding_id="FND-001",
            test_id=TEST,
        )


def test_accepts_fresh_matching_failed_regression_evidence():
    validate_evidence(
        record(),
        current_head=HEAD,
        current_workspace=FP,
        expected_success=False,
        finding_id="FND-001",
        test_id=TEST,
    )


@pytest.mark.parametrize("approval", [
    None, {}, "approved", [],
    {"mode": "full", "critical_related_approved": True, "source": "user", "approved_at": "now"},
    {"mode": "related", "critical_related_approved": False, "source": "user", "approved_at": "now"},
    {"mode": "related", "critical_related_approved": 1, "source": "user", "approved_at": "now"},
    {"mode": "related", "critical_related_approved": "true", "source": "user", "approved_at": "now"},
    {"mode": "related", "critical_related_approved": True, "source": "agent", "approved_at": "now"},
    {"mode": "related", "critical_related_approved": True, "source": "user", "approved_at": ""},
    {"mode": "related", "critical_related_approved": True, "source": "user", "approved_at": "  "},
    {"mode": "related", "critical_related_approved": True, "source": "user", "approved_at": 123},
])
def test_single_critical_related_requires_explicit_approval(approval):
    evidence = record(exit_code=0, scope="related", covered_tests=[TEST])
    finding = {"id": "FND-001", "severity": "critical", "closure": approval}
    with pytest.raises(EvidenceValidationError, match="^CRITICAL_RELATED_APPROVAL_REQUIRED$"):
        validate_finding_closure_evidence(
            finding, evidence, {"impact": {"required_tests": [TEST]}},
            current_head=HEAD, current_workspace=FP,
        )


@pytest.mark.parametrize("severity,scope,approval", [
    ("critical", "related", {"mode": "related", "critical_related_approved": True,
                               "source": "user", "approved_at": "2000-01-01"}),
    ("major", "related", "not an approval"),
])
def test_single_closure_preserves_approved_and_noncritical_paths(severity, scope, approval):
    validate_finding_closure_evidence(
        {"id": "FND-001", "severity": severity, "closure": approval},
        record(exit_code=0, scope=scope, covered_tests=[TEST]),
        {"impact": {"required_tests": [TEST]}}, current_head=HEAD, current_workspace=FP,
    )


def test_single_closure_keeps_existing_full_scope_schema_rejection():
    # Current receipt schema permits only related; do not expand it for this fix.
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_SCHEMA_INVALID"):
        validate_finding_closure_evidence(
            {"severity": "critical"}, record(exit_code=0, scope="full"),
            {"impact": {"required_tests": [TEST]}}, current_head=HEAD, current_workspace=FP,
        )


def test_major_closure_accepts_related_evidence_covering_impact_tests():
    evidence = record(
        exit_code=0,
        scope="related",
        covered_tests=[TEST, "tests/test_api.py::test_save"],
    )
    finding = {"id": "FND-001", "severity": "major"}
    impact = {
        "impact": {
            "required_tests": [TEST, "tests/test_api.py::test_save"],
            "full_suite": {"recommended": False},
        }
    }
    validate_finding_closure_evidence(
        finding, evidence, impact, current_head=HEAD, current_workspace=FP
    )


def test_major_closure_rejects_missing_related_coverage():
    evidence = record(exit_code=0, scope="related", covered_tests=[TEST])
    finding = {"id": "FND-001", "severity": "major"}
    impact = {
        "impact": {
            "required_tests": [TEST, "tests/test_api.py::test_save"],
            "full_suite": {"recommended": False},
        }
    }
    with pytest.raises(EvidenceValidationError, match="RELATED_TEST_COVERAGE_MISSING"):
        validate_finding_closure_evidence(
            finding, evidence, impact, current_head=HEAD, current_workspace=FP
        )


def test_major_closure_ignores_advisory_full_suite_recommendation():
    evidence = record(exit_code=0, scope="related", covered_tests=[TEST])
    finding = {"id": "FND-001", "severity": "major"}
    impact = {"impact": {"required_tests": [TEST]}}
    validate_finding_closure_evidence(
        finding, evidence, impact, current_head=HEAD, current_workspace=FP
    )

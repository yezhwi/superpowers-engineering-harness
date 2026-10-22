"""Validated, immutable candidate projection shared by existing assessors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import ValidationError, validate

from harness import source_access
from harness.evidence_validator import EvidenceValidationError, validate_evidence
from harness.schema_resources import read_schema


DOMAIN = "harness:candidate-assessment:v1"
POLICY = {
    "format": "candidate-commit/v1",
    "capability_version": 1,
    "minimum_reader": "0.3.2",
}
SEMANTIC_SOURCES = (
    "alignment.yaml",
    "impact.yaml",
    "invariants.yaml",
    "plan-execution.yaml",
    "plan.yaml",
    "requirements.yaml",
    "gate.yaml",
    "observability.yaml",
)
REVIEW_KINDS = frozenset({"complexity", "diagnosability", "interface"})


class CandidateAssessmentError(ValueError):
    pass


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _safe_reference(reference: str) -> str:
    if not isinstance(reference, str):
        raise CandidateAssessmentError("CANDIDATE_EVIDENCE_REFERENCE_INVALID")
    path = PurePosixPath(reference)
    if path.is_absolute() or ".." in path.parts:
        raise CandidateAssessmentError("CANDIDATE_EVIDENCE_REFERENCE_INVALID")
    if path.parts[:2] == (".harness", "evidence"):
        return path.as_posix()
    if path.parts and path.parts[0] != ".harness":
        return (PurePosixPath(".harness/evidence") / path).as_posix()
    raise CandidateAssessmentError("CANDIDATE_EVIDENCE_REFERENCE_INVALID")


def _task_semantics(task: dict) -> dict:
    """Keep business inputs and remove mutable lifecycle/authority bookkeeping."""
    return {
        "task": {key: (task.get("task") or {}).get(key) for key in ("id", "type")},
        "risk": {
            key: (task.get("risk") or {}).get(key)
            for key in ("level", "profile", "dimensions")
        },
        "scope": task.get("scope"),
        "git": {
            key: (task.get("git") or {}).get(key)
            for key in ("base_ref", "base_commit", "head_at_start")
        },
        "plan_reconciliation": task.get("plan_reconciliation"),
        "verification_mode": task.get("verification_mode"),
        "existing_verification": task.get("existing_verification"),
    }


def require_candidate_policy(harness_dir: Path) -> None:
    """Enrollment belongs to the Gate contract, never its derived task summary."""
    try:
        document = yaml.safe_load(source_access.read_regular_bytes_beneath(
            harness_dir / 'gate.yaml', harness_dir))
        validate(document, read_schema("gate.schema.json"))
    except (OSError, ValueError, yaml.YAMLError, ValidationError) as exc:
        raise CandidateAssessmentError("CANDIDATE_POLICY_REQUIRED") from exc
    if document["gate"].get("candidate_commit") != POLICY:
        raise CandidateAssessmentError("CANDIDATE_POLICY_REQUIRED")
    if (document['gate'].get('architecture') or {}).get('mode', 'off') != 'off':
        # Existing architecture assessment reads the live worktree. Until that
        # domain has a candidate-export adapter, refuse rather than attest it.
        raise CandidateAssessmentError('CANDIDATE_UNSUPPORTED')


def _specification_projection(name: str, document: object) -> object:
    """Remove only proof/progress fields that necessarily change after execution."""
    if not isinstance(document, dict):
        raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
    if name == "requirements.yaml":
        return {
            "requirements": [
                {key: value for key, value in item.items() if key not in {"status", "evidence"}}
                for item in document.get("requirements", [])
            ]
        }
    if name == "invariants.yaml":
        return {
            "invariants": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"status", "verification"}
                }
                for item in document.get("invariants", [])
            ]
        }
    if name == "plan-execution.yaml":
        return {
            "version": document.get("version"),
            "plan": document.get("plan"),
        }
    return document


def _control_document(harness_dir: Path, name: str):
    try:
        return yaml.safe_load(source_access.read_regular_bytes_beneath(harness_dir / name, harness_dir))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CandidateAssessmentError('CANDIDATE_SOURCE_INVALID') from exc


def semantic_source_snapshot(harness_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    task = _control_document(harness_dir, 'current-task.yaml')
    if not isinstance(task, dict):
        raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
    result["current-task.yaml"] = _digest(_canonical(_task_semantics(task)))
    for name in SEMANTIC_SOURCES:
        path = harness_dir / name
        if source_access.exists(path):
            try:
                document = _control_document(harness_dir, name)
            except (UnicodeError, yaml.YAMLError) as exc:
                raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID") from exc
            result[name] = _digest(
                _canonical(_specification_projection(name, document))
            )
    alignment_path = harness_dir / "alignment.yaml"
    if source_access.exists(alignment_path):
        try:
            alignment = _control_document(harness_dir, 'alignment.yaml')
        except (UnicodeError, yaml.YAMLError) as exc:
            raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID") from exc
        if not isinstance(alignment, dict):
            raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
        for key, directory, prefix in (
            ("decision_ids", "decisions", "DEC"),
            ("interface_contract_ids", "interface-contracts", "INT"),
        ):
            values = alignment.get(key) or []
            if not isinstance(values, list):
                raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
            for identifier in values:
                if (
                    not isinstance(identifier, str)
                    or not identifier.startswith(prefix + "-")
                    or not identifier[len(prefix) + 1 :].isdigit()
                ):
                    raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
                path = harness_dir / directory / f"{identifier}.yaml"
                try:
                    document = _control_document(harness_dir, f'{directory}/{identifier}.yaml')
                except (OSError, UnicodeError, yaml.YAMLError) as exc:
                    raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID") from exc
                if not isinstance(document, dict) or document.get("id") != identifier:
                    raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
                if directory == "decisions" and document.get("status") != "ACCEPTED":
                    raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
                projection = (
                    {
                        field: value
                        for field, value in document.items()
                        if field != "verification"
                    }
                    if directory == "interface-contracts"
                    else document
                )
                name = f"{directory}/{identifier}.yaml"
                result[name] = _digest(_canonical(projection))
    return result


def derive_qualification(repo: Path, candidate: dict, evidence_type: str, executed: list[str]):
    """Shared read-only binding derivation; never imports or executes the runner."""
    harness = repo / '.harness'
    if candidate.get('semantic_sources') != semantic_source_snapshot(harness):
        raise CandidateAssessmentError('CANDIDATE_DRIFT')
    try:
        documents = {}
        for name, schema in (('requirements', 'requirement'), ('invariants', 'invariant'), ('plan', 'plan')):
            document = _control_document(harness, name + '.yaml')
            validate(document, read_schema(schema + '.schema.json'))
            documents[name] = document
        alignment = _control_document(harness, 'alignment.yaml')
        strategies = {'unit_test': {'unit', 'regression'}, 'integration_test': {'integration', 'e2e', 'concurrency'},
                      'contract_test': {'contract'}, 'security': {'security'}}[evidence_type]
        bindings, tests_covered, cases_covered = [], set(), set()
        for kind, prefix in (('requirements', 'REQ-'), ('invariants', 'INV-')):
            for obligation in documents[kind].get(kind, []):
                if not obligation['id'].startswith(prefix):
                    raise ValueError('invalid obligation')
                for case in (obligation.get('test_plan') or {}).get('cases', []):
                    tests = case.get('tests') or []
                    if case.get('strategy') not in strategies or not tests:
                        continue
                    groups = [[node for node in executed if node == test or node.startswith(test + '[')] for test in tests]
                    if any(not group for group in groups):
                        continue
                    bindings.append({'case_ref': obligation['id'] + '/' + case['id'],
                                     'obligation_ref': obligation['id'], 'tests': sorted(tests),
                                     'executed_nodes': sorted({node for group in groups for node in group})})
                    tests_covered.update(tests)
                    cases_covered.add(case['id'])
        case_refs = {binding['case_ref'] for binding in bindings}
        items = documents['plan'].get('items', [])
        plan_items = sorted(item['id'] for item in items if set(item.get('test_case_refs') or []) & case_refs)
        required = {reference for item in items for reference in item.get('test_case_refs', [])}
        interfaces = []
        if required and required <= case_refs:
            values = (alignment or {}).get('interface_contract_ids') or []
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.startswith('INT-')
                                                  or not value[4:].isdigit() for value in values):
                raise ValueError('invalid interfaces')
            interfaces = sorted(set(values))
        return (sorted(tests_covered), sorted(cases_covered),
                sorted(bindings, key=lambda binding: binding['case_ref']), plan_items, interfaces)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, yaml.YAMLError, ValidationError) as exc:
        raise CandidateAssessmentError('CANDIDATE_PROOF_UNQUALIFIED') from exc


@dataclass(frozen=True)
class CandidateEvidenceSource:
    reference: str
    record_json: str
    requirements: frozenset[str]
    invariants: frozenset[str]
    interfaces: frozenset[str]
    plan_items: frozenset[str]

    def record(self) -> dict:
        return json.loads(self.record_json)


@dataclass(frozen=True)
class CandidateReviewSource:
    kind: str
    reference: str
    report_json: str
    record_json: str

    def report(self) -> dict:
        return json.loads(self.report_json)

    def record(self) -> dict:
        return json.loads(self.record_json)


@dataclass(frozen=True)
class CandidateAssessmentView:
    candidate_id: str
    parent_commit: str
    candidate_tree: str
    export_fingerprint: str
    changed_paths: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    review_scope: tuple[str, ...] = ()
    proof_ids: tuple[str, ...] = ()
    review_ids: tuple[str, ...] = ()
    semantic_sources: tuple[tuple[str, str], ...] = ()
    covered_requirements: frozenset[str] = field(default_factory=frozenset)
    covered_invariants: frozenset[str] = field(default_factory=frozenset)
    covered_interfaces: frozenset[str] = field(default_factory=frozenset)
    covered_plan_items: frozenset[str] = field(default_factory=frozenset)
    covered_cases: frozenset[str] = field(default_factory=frozenset)
    covered_evidence_types: frozenset[str] = field(default_factory=frozenset)
    evidence_sources: tuple[CandidateEvidenceSource, ...] = ()
    review_sources: tuple[CandidateReviewSource, ...] = ()
    domain: str = DOMAIN

    def qualifies_requirement(self, identifier: str, cases: tuple[str, ...]) -> bool:
        return identifier in self.covered_requirements and {
            f"{identifier}/{case}" for case in cases
        } <= self.covered_cases

    def qualifies_invariant(self, identifier: str, cases: tuple[str, ...]) -> bool:
        return identifier in self.covered_invariants and {
            f"{identifier}/{case}" for case in cases
        } <= self.covered_cases

    def qualifies_interface(self, identifier: str) -> bool:
        return identifier in self.covered_interfaces

    def resolve_evidence(
        self,
        reference: str,
        *,
        requirement_id: str | None = None,
        invariant_id: str | None = None,
        interface_id: str | None = None,
        plan_item_id: str | None = None,
    ) -> dict | None:
        try:
            namespaced = _safe_reference(reference)
        except CandidateAssessmentError:
            return None
        for source in self.evidence_sources:
            if source.reference != namespaced:
                continue
            if requirement_id is not None and requirement_id not in source.requirements:
                return None
            if invariant_id is not None and invariant_id not in source.invariants:
                return None
            if interface_id is not None and interface_id not in source.interfaces:
                return None
            if plan_item_id is not None and plan_item_id not in source.plan_items:
                return None
            return source.record()
        return None

    def evidence_records(self) -> tuple[dict, ...]:
        return tuple(source.record() for source in self.evidence_sources)

    def review_record(self, kind: str) -> dict | None:
        return next(
            (source.record() for source in self.review_sources if source.kind == kind),
            None,
        )

    def review_report(self, kind: str) -> dict | None:
        return next(
            (source.report() for source in self.review_sources if source.kind == kind),
            None,
        )


def _id(record: dict, field: str, domain: bytes, path: Path) -> str:
    projection = dict(record)
    identifier = projection.pop(field, None)
    expected = _digest(domain + _canonical(projection))
    if identifier != expected or path.name != f"{expected[7:]}.json":
        raise CandidateAssessmentError("CANDIDATE_RECORD_HASH_INVALID")
    return expected


def _assessment_evidence_record(
    raw: dict, *, tree: str, source_fingerprint: str
) -> dict:
    if any(
        key in raw
        for key in ("commit", "workspace_fingerprint", "workspace_fingerprint_after")
    ):
        raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
    record = dict(raw)
    record.update(
        {
            "commit": tree,
            "workspace_fingerprint": source_fingerprint,
            "workspace_fingerprint_after": source_fingerprint,
        }
    )
    return record


def _assessment_review_record(
    raw: dict, *, tree: str, source_fingerprint: str
) -> dict:
    if any(
        key in raw
        for key in ("commit", "workspace_fingerprint", "workspace_fingerprint_after")
    ):
        raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED")
    record = {
        key: value
        for key, value in raw.items()
        if key not in {"candidate_tree", "execution_domain", "source_fingerprint"}
    }
    record.update(
        {
            "commit": tree,
            "workspace_fingerprint": source_fingerprint,
            "workspace_fingerprint_after": source_fingerprint,
        }
    )
    return record


def _bound_document(harness_dir, name, schema, identifier, domain):
    path = harness_dir / name
    raw = source_access.read_regular_bytes_beneath(path, harness_dir)
    document = json.loads(raw)
    validate(document, read_schema(schema))
    _id(document, identifier, domain, path)
    return document


def historical_candidate_metadata(harness_dir: Path, operation: dict):
    """Validate captured immutable sources without live workspace/grant freshness."""
    try:
        validate(operation, read_schema('candidate-operation.schema.json'))
        payload = operation['payload']
        task = yaml.safe_load(source_access.read_regular_bytes_beneath(
            harness_dir / 'current-task.yaml', harness_dir))
        if task['task']['id'] != payload['task_id']:
            raise ValueError('task mismatch')
        candidate_ref = 'evidence/candidate-prepared/' + payload['candidate_id'][7:] + '.json'
        acceptance_ref = 'evidence/candidate-acceptance/' + payload['acceptance_id'][7:] + '.json'
        candidate = _bound_document(harness_dir, candidate_ref, 'candidate-prepared.schema.json',
                                    'candidate_id', b'harness:candidate-prepared:v1\0')
        acceptance = _bound_document(harness_dir, acceptance_ref, 'candidate-acceptance.schema.json',
                                     'acceptance_id', b'harness:candidate-acceptance:v1\0')
        if (candidate['candidate_id'] != payload['candidate_id']
                or acceptance['acceptance_id'] != payload['acceptance_id']
                or acceptance['candidate_id'] != payload['candidate_id']
                or candidate['candidate_tree'] != payload['tree']
                or acceptance['candidate_tree'] != payload['tree']
                or candidate['parent'] != payload['parent']
                or acceptance['parent_commit'] != payload['parent']
                or candidate['full_ref'] != payload['full_ref']):
            raise ValueError('historical identity mismatch')
        expected = {candidate_ref, acceptance_ref}
        expected.update(_safe_reference(ref).removeprefix('.harness/') for ref in acceptance['evidence_refs'])
        if not expected <= payload['accepted_sources'].keys():
            raise ValueError('missing captured source')
        namespaces = {'candidate-prepared', 'candidate-proof', 'candidate-review', 'candidate-acceptance'}
        for name, fingerprint in payload['accepted_sources'].items():
            path = PurePosixPath(name)
            if (len(path.parts) != 3 or path.parts[0] != 'evidence' or path.parts[1] not in namespaces
                    or path.suffix != '.json' or len(path.stem) != 64
                    or set(path.stem) - set('0123456789abcdef')
                    or path.as_posix() != name):
                raise ValueError('unknown historical source')
            if _digest(source_access.read_regular_bytes_beneath(harness_dir / name, harness_dir)) != fingerprint:
                raise ValueError('historical source changed')
        return task, candidate, acceptance
    except (OSError, ValueError, TypeError, KeyError, ValidationError, yaml.YAMLError) as exc:
        raise CandidateAssessmentError('CANDIDATE_HISTORY_INVALID') from exc


def candidate_context_projection(harness_dir: Path, current_head: str):
    """Separate validated historical records from unassessed current readiness."""
    from .git_query import GitQueryError, run_git_query
    from .transaction_recovery import PublicationAdmissionError, candidate_operations

    pointer_path = harness_dir / '.candidate-active.json'
    if not source_access.exists(pointer_path):
        return None
    require_candidate_policy(harness_dir)
    try:
        pointer = json.loads(source_access.read_regular_bytes_beneath(pointer_path, harness_dir))
        task = _control_document(harness_dir, 'current-task.yaml')
        if (not isinstance(pointer, dict) or set(pointer) != {'schema', 'task_id', 'candidate_id'}
                or pointer['schema'] != 'candidate-active/v1' or pointer['task_id'] != task['task']['id']):
            raise ValueError('candidate pointer mismatch')
        identifier = pointer['candidate_id']
        if (not isinstance(identifier, str) or len(identifier) != 71 or not identifier.startswith('sha256:')
                or set(identifier[7:]) - set('0123456789abcdef')):
            raise ValueError('invalid candidate id')
        candidate_ref = 'evidence/candidate-prepared/' + identifier[7:] + '.json'
        candidate = _bound_document(harness_dir, candidate_ref, 'candidate-prepared.schema.json',
                                    'candidate_id', b'harness:candidate-prepared:v1\0')
        accepted = []
        directory = harness_dir / 'evidence/candidate-acceptance'
        for path in source_access.members(directory, '*.json'):
            record = _bound_document(harness_dir, path.relative_to(harness_dir), 'candidate-acceptance.schema.json',
                                     'acceptance_id', b'harness:candidate-acceptance:v1\0')
            if record['candidate_id'] == identifier:
                if record['parent_commit'] != candidate['parent'] or record['candidate_tree'] != candidate['candidate_tree']:
                    raise ValueError('acceptance mismatch')
                accepted.append(record['acceptance_id'])
        if len(accepted) > 1:
            raise ValueError('ambiguous acceptance')
        proposed = []
        operations = []
        for operation in candidate_operations(harness_dir):
            payload = operation['payload']
            if payload['candidate_id'] != identifier:
                continue
            _, _, acceptance = historical_candidate_metadata(harness_dir, operation)
            if acceptance['acceptance_id'] not in accepted:
                raise ValueError('uncaptured acceptance')
            operations.append({'operation_id': operation['operation_id'], 'phase': operation['phase']})
            if operation['phase'] != 'TRACE_PUBLISHED':
                continue
            trace_path = harness_dir / 'evidence/candidate-trace' / (operation['operation_id'][7:] + '.json')
            trace = json.loads(source_access.read_regular_bytes_beneath(trace_path, harness_dir))
            validate(trace, read_schema('candidate-trace.schema.json'))
            if (trace['acceptance_id'] != payload['acceptance_id'] or trace['parent'] != payload['parent']):
                raise ValueError('trace identity mismatch')
            for suffix, expected in (('^{tree}', payload['tree']), ('^', payload['parent'])):
                query = run_git_query(harness_dir.parent, ('rev-parse', '--verify', payload['proposed'] + suffix))
                if query.returncode or query.stdout.decode().strip() != expected:
                    raise ValueError('historical commit mismatch')
            proposed.append(payload['proposed'])
        return {'candidate_id': identifier, 'parent_commit': candidate['parent'],
                'historical_acceptance': bool(accepted), 'acceptance_ids': accepted,
                'historically_committed': bool(proposed), 'operations': operations,
                'live_parent': current_head == candidate['parent'], 'live_proposed': current_head in proposed,
                'current_readiness': 'NOT_ASSESSED', 'generic_evidence_reuse': False}
    except (OSError, ValueError, TypeError, KeyError, ValidationError, yaml.YAMLError,
            GitQueryError, PublicationAdmissionError) as exc:
        raise CandidateAssessmentError('CANDIDATE_HISTORY_INVALID') from exc


def active_assessment_view(harness_dir: Path, *, require_reviews: bool = True):
    """Resolve the task's explicit preparation pointer; never guess latest evidence."""
    gate_path = harness_dir / 'gate.yaml'
    if not source_access.exists(gate_path):
        return None
    gate = _control_document(harness_dir, 'gate.yaml')
    if not isinstance(gate, dict) or 'candidate_commit' not in (gate.get('gate') or {}):
        return None
    require_candidate_policy(harness_dir)
    try:
        pointer = json.loads(source_access.read_regular_bytes_beneath(harness_dir / '.candidate-active.json', harness_dir))
        task = _control_document(harness_dir, 'current-task.yaml')
        if (not isinstance(pointer, dict) or set(pointer) != {'schema', 'task_id', 'candidate_id'}
                or pointer['schema'] != 'candidate-active/v1'
                or pointer['task_id'] != task.get('task', {}).get('id')):
            raise ValueError('candidate pointer mismatch')
        identifier = pointer['candidate_id']
        if (not isinstance(identifier, str) or len(identifier) != 71 or not identifier.startswith('sha256:')
                or set(identifier[7:]) - set('0123456789abcdef')):
            raise ValueError('candidate identity invalid')
        path = harness_dir / 'evidence/candidate-prepared' / (identifier[7:] + '.json')
        candidate = json.loads(source_access.read_regular_bytes_beneath(path, harness_dir))
        validate(candidate, read_schema('candidate-prepared.schema.json'))
        _id(candidate, 'candidate_id', b'harness:candidate-prepared:v1\0', path)
        groups = []
        for directory in ('candidate-proof', 'candidate-review'):
            parent = harness_dir / 'evidence' / directory
            records = tuple((path, json.loads(source_access.read_regular_bytes_beneath(path, harness_dir)))
                            for path in source_access.members(parent, '*.json'))
            groups.append(tuple((path, record) for path, record in records if record.get('candidate_id') == identifier))
        return build_candidate_assessment_view(harness_dir.parent, candidate, *groups,
                                               require_reviews=require_reviews)
    except (OSError, ValueError, TypeError, KeyError, ValidationError, yaml.YAMLError) as exc:
        raise CandidateAssessmentError('CANDIDATE_PROOF_UNQUALIFIED') from exc


def build_candidate_assessment_view(
    root: Path,
    candidate: dict,
    proofs: tuple[tuple[Path, dict], ...],
    reviews: tuple[tuple[Path, dict], ...],
    *,
    require_reviews: bool = True,
) -> CandidateAssessmentView:
    harness = root / ".harness"
    task = _control_document(harness, 'current-task.yaml')
    if not isinstance(task, dict):
        raise CandidateAssessmentError("CANDIDATE_SOURCE_INVALID")
    require_candidate_policy(harness)
    candidate_id = candidate.get("candidate_id")
    parent = candidate.get("parent")
    tree = candidate.get("candidate_tree")
    if (
        candidate.get("schema") != "candidate-prepared/v1"
        or candidate.get("domain") != "harness:candidate-prepared:v1"
        or not isinstance(candidate_id, str)
        or not isinstance(parent, str)
        or len(parent) != 40
        or not isinstance(tree, str)
        or len(tree) != 40
    ):
        raise CandidateAssessmentError("CANDIDATE_PREPARED_INVALID")
    selected = candidate.get("selected")
    if not isinstance(selected, list) or not selected:
        raise CandidateAssessmentError("CANDIDATE_PREPARED_INVALID")
    changed = tuple(sorted(item.get("path") for item in selected if isinstance(item, dict) and isinstance(item.get("path"), str)))
    if len(changed) != len(selected):
        raise CandidateAssessmentError("CANDIDATE_PREPARED_INVALID")
    source_snapshot = semantic_source_snapshot(harness)
    if candidate.get("semantic_sources") != source_snapshot:
        raise CandidateAssessmentError("CANDIDATE_SOURCE_CHANGED")

    proof_ids: list[str] = []
    refs: list[str] = []
    requirements: set[str] = set()
    invariants: set[str] = set()
    interfaces: set[str] = set()
    plan_items: set[str] = set()
    cases: set[str] = set()
    evidence_types: set[str] = set()
    fingerprints: set[str] = set()
    evidence_sources: list[CandidateEvidenceSource] = []
    for path, proof in proofs:
        if proof.get("candidate_id") != candidate_id:
            continue
        if proof.get("schema") != "candidate-proof/v1" or proof.get("domain") != "harness:candidate-proof:v1":
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        try:
            validate(proof, read_schema("candidate-proof.schema.json"))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED") from exc
        proof_ids.append(_id(proof, "proof_id", b"harness:candidate-proof:v1\0", path))
        execution = proof.get("execution") or {}
        qualification = proof.get("qualification") or {}
        if (
            execution.get("exit_code") != 0
            or execution.get("candidate_tree") != tree
            or execution.get("parent_commit") != parent
            or execution.get("source_before") != execution.get("source_after")
            or not isinstance(execution.get("runtime"), dict)
            or not isinstance(execution.get("dependencies"), dict)
            or not isinstance(execution.get("source_config"), dict)
            or qualification.get("coverage_complete") is not True
            or qualification.get("profile_version") != "candidate-proof-profile/v1"
        ):
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        export = execution.get("source_before")
        if not isinstance(export, str) or not export.startswith("sha256:"):
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        fingerprints.add(export)
        reference = _safe_reference(path.relative_to(root).as_posix())
        raw_record = proof.get("record")
        if (
            not isinstance(raw_record, dict)
            or raw_record.get("candidate_tree") != tree
            or raw_record.get("source_fingerprint") != export
            or raw_record.get("execution_domain") != "outside-git"
        ):
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        profile = execution.get("profile")
        evidence_type = qualification.get("evidence_type")
        if profile == "pytest-junit-v1":
            try:
                covered_tests, covered_cases, bindings, derived_plan, derived_interfaces = (
                    derive_qualification(
                        root,
                        candidate,
                        evidence_type,
                        raw_record.get("executed_tests") or [],
                    )
                )
            except (CandidateAssessmentError, ValueError) as exc:
                raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED") from exc
            expected_qualification = {
                "coverage_complete": True,
                "profile_version": "candidate-proof-profile/v1",
                "evidence_type": evidence_type,
                "bindings": bindings,
                "interfaces": derived_interfaces,
                "plan_items": derived_plan,
            }
            if (
                raw_record.get("covered_tests") != covered_tests
                or raw_record.get("covered_test_cases") != covered_cases
            ):
                raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        else:
            expected_type = {
                "python-module-build-v1": "build",
                "python-script-v1": "custom",
            }.get(profile)
            expected_qualification = {
                "coverage_complete": True,
                "profile_version": "candidate-proof-profile/v1",
                "evidence_type": expected_type,
                "bindings": [],
                "interfaces": [],
                "plan_items": [],
            }
            if (
                raw_record.get("covered_tests")
                or raw_record.get("covered_test_cases")
                or raw_record.get("executed_tests")
            ):
                raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        if qualification != expected_qualification:
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        record = _assessment_evidence_record(
            raw_record, tree=tree, source_fingerprint=export
        )
        try:
            validate_evidence(
                record,
                current_head=tree,
                current_workspace=export,
                expected_success=True,
            )
        except EvidenceValidationError as exc:
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED") from exc
        proof_requirements: set[str] = set()
        proof_invariants: set[str] = set()
        for binding in qualification["bindings"]:
            obligation = binding["obligation_ref"]
            if obligation.startswith("REQ-"):
                requirements.add(obligation)
                proof_requirements.add(obligation)
            else:
                invariants.add(obligation)
                proof_invariants.add(obligation)
            cases.add(binding["case_ref"])
        interfaces.update(qualification["interfaces"])
        plan_items.update(qualification["plan_items"])
        evidence_types.add(qualification["evidence_type"])
        if {qualification["evidence_type"]} != {record.get("type")}:
            raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
        evidence_sources.append(
                CandidateEvidenceSource(
                    reference,
                    _canonical(record).decode(),
                    frozenset(proof_requirements),
                    frozenset(proof_invariants),
                frozenset(qualification["interfaces"]),
                frozenset(qualification["plan_items"]),
            )
        )
        refs.append(reference)
    if not proof_ids or len(fingerprints) != 1:
        raise CandidateAssessmentError("CANDIDATE_PROOF_UNQUALIFIED")
    review_ids: list[str] = []
    kinds: set[str] = set()
    review_scope: set[str] = set()
    review_sources: list[CandidateReviewSource] = []
    for path, review in reviews:
        if review.get("candidate_id") != candidate_id:
            continue
        if review.get("schema") != "candidate-review/v1" or review.get("domain") != "harness:candidate-review:v1":
            raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED")
        try:
            validate(review, read_schema("candidate-review.schema.json"))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED") from exc
        review_ids.append(_id(review, "review_id", b"harness:candidate-review:v1\0", path))
        kind = review.get("kind")
        qualification = review.get("qualification") or {}
        if (
            kind not in REVIEW_KINDS
            or qualification.get("candidate_tree") != tree
            or qualification.get("parent_commit") != parent
            or qualification.get("outcome") != "PASS"
            or qualification.get("source_fingerprint") not in fingerprints
            or qualification.get("scope_complete") is not True
        ):
            raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED")
        paths = qualification.get("review_scope")
        if not isinstance(paths, list) or any(not isinstance(value, str) for value in paths):
            raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED")
        raw_record = review.get("record")
        report = review.get("report")
        if (
            not isinstance(raw_record, dict)
            or not isinstance(report, dict)
            or raw_record.get("candidate_tree") != tree
            or raw_record.get("source_fingerprint")
            != qualification["source_fingerprint"]
            or raw_record.get("execution_domain") != "outside-git"
            or kind in kinds
        ):
            raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED")
        record = _assessment_review_record(
            raw_record,
            tree=tree,
            source_fingerprint=qualification["source_fingerprint"],
        )
        try:
            validate_evidence(
                record,
                current_head=tree,
                current_workspace=qualification["source_fingerprint"],
                expected_success=True,
            )
        except EvidenceValidationError as exc:
            raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED") from exc
        try:
            if kind == "complexity":
                from .complexity import (
                    validate_complexity_checks,
                    validate_complexity_finding,
                )

                validate_complexity_checks(report)
                validate_complexity_checks(record)
                for finding in report.get("findings", []):
                    validate_complexity_finding(finding)
                if (
                    report.get("checks") != record.get("checks")
                    or any(
                        check["result"] == "fail"
                        for check in report["checks"].values()
                    )
                    or any(
                        finding["status"] == "open"
                        and finding["severity"] == "high"
                        for finding in report.get("findings", [])
                    )
                ):
                    raise ValueError("complexity review is not PASS")
            elif kind == "diagnosability":
                from .diagnosability import (
                    validate_review_evidence,
                    validate_review_input,
                )

                task_id = (task.get("task") or {}).get("id")
                validate_review_input(report, task_id=task_id)
                validate_review_evidence(record)
                if report.get("checks") != record.get("checks") or any(
                    value == "fail" for value in record.get("checks", {}).values()
                ):
                    raise ValueError("diagnosability review is not PASS")
            else:
                from .interface_review import validate_review_report

                validate_review_report(harness, report, task_id=task["task"]["id"])
                if (
                    report.get("checks") != record.get("checks")
                    or set(report.get("contracts") or [])
                    != set(record.get("contracts") or [])
                    or any(
                        value == "fail" for value in record.get("checks", {}).values()
                    )
                ):
                    raise ValueError("interface review is not PASS")
        except (ValidationError, ValueError) as exc:
            raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED") from exc
        reference = _safe_reference(path.relative_to(root).as_posix())
        kinds.add(kind)
        review_scope.update(paths)
        review_sources.append(
            CandidateReviewSource(
                kind,
                reference,
                _canonical(report).decode(),
                _canonical(record).decode(),
            )
        )
        refs.append(reference)
    if require_reviews and kinds != REVIEW_KINDS:
        raise CandidateAssessmentError("CANDIDATE_REVIEW_UNQUALIFIED")

    return CandidateAssessmentView(
        candidate_id=candidate_id,
        parent_commit=parent,
        candidate_tree=tree,
        export_fingerprint=next(iter(fingerprints)),
        changed_paths=changed,
        evidence_refs=tuple(sorted(refs)),
        review_scope=tuple(sorted(review_scope)),
        proof_ids=tuple(sorted(proof_ids)),
        review_ids=tuple(sorted(review_ids)),
        semantic_sources=tuple(sorted(source_snapshot.items())),
        covered_requirements=frozenset(requirements),
        covered_invariants=frozenset(invariants),
        covered_interfaces=frozenset(interfaces),
        covered_plan_items=frozenset(plan_items),
        covered_cases=frozenset(cases),
        covered_evidence_types=frozenset(evidence_types),
        evidence_sources=tuple(evidence_sources),
        review_sources=tuple(review_sources),
    )

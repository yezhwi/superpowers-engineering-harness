"""Batch-only immutable receipt loading; legacy single-proof I/O stays unchanged."""
import hashlib
import json
from pathlib import Path

from . import source_access
from .evidence_validator import EvidenceValidationError, validate_finding_closure_batch
from .paths import evidence_path

_MAX_RECEIPT = 4 * 1024 * 1024
_MAX_TOTAL = 16 * 1024 * 1024


def _invalid(code='BATCH_EVIDENCE_INVALID'):
    raise EvidenceValidationError(code)


def closure_proof_kind(finding):
    single, batch = 'evidence' in finding, 'closure_evidence' in finding
    if single == batch:
        _invalid('FINDING_CLOSURE_FORMAT_INVALID')
    if single:
        if not isinstance(finding['evidence'], str) or not finding['evidence']:
            _invalid('FINDING_CLOSURE_FORMAT_INVALID')
        return 'single'
    value = finding['closure_evidence']
    if (not isinstance(value, dict) or set(value) != {'version', 'receipts'}
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['receipts'], list) or not 2 <= len(value['receipts']) <= 64):
        _invalid('FINDING_CLOSURE_FORMAT_INVALID')
    for receipt in value['receipts']:
        if (not isinstance(receipt, dict) or set(receipt) != {'ref', 'sha256'}
                or not isinstance(receipt['ref'], str) or not receipt['ref']
                or not isinstance(receipt['sha256'], str) or len(receipt['sha256']) != 71
                or not receipt['sha256'].startswith('sha256:')
                or any(c not in '0123456789abcdef' for c in receipt['sha256'][7:])):
            _invalid('FINDING_CLOSURE_FORMAT_INVALID')
    return 'batch'


def _snapshot(root, reference):
    if not isinstance(reference, str) or not reference:
        _invalid()
    candidate = Path(reference)
    if '..' in candidate.parts:
        _invalid()
    if len(candidate.parts) == 1 and not candidate.is_absolute():
        candidate = root / 'evidence' / (reference if candidate.suffix == '.json' else reference + '.json')
    elif not candidate.is_absolute():
        candidate = root.parent / candidate
    # Workspace ancestors may have alias spellings; the .harness boundary itself
    # and receipt components still must not be symlinks.
    root_identity = source_access.node_identity_beneath(root, root, node_kind='directory')['identity']
    physical_root = root.resolve()
    if source_access.node_identity_beneath(physical_root, physical_root, node_kind='directory')['identity'] != root_identity:
        _invalid('BATCH_EVIDENCE_CHANGED')
    read_root = root if candidate.is_relative_to(root) else physical_root
    # Read original receipt spelling before evidence_path resolves it.
    snapshot = source_access.read_regular_snapshot_beneath(candidate, read_root, max_bytes=_MAX_RECEIPT)
    canonical = evidence_path(root, reference)
    if canonical.parent != physical_root / 'evidence':
        _invalid()
    resolved = source_access.read_regular_snapshot_beneath(canonical, physical_root, max_bytes=_MAX_RECEIPT)
    if ([resolved.device, resolved.inode] != [snapshot.device, snapshot.inode]
            or resolved.content != snapshot.content
            or source_access.node_identity_beneath(root, root, node_kind='directory')['identity'] != root_identity):
        _invalid('BATCH_EVIDENCE_CHANGED')
    return root / 'evidence' / canonical.name, snapshot


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _invalid()
        result[key] = value
    return result


def prepare_closure_proof(root, finding, references, impact, *, current_head, current_workspace):
    root = Path(root).absolute()
    if not isinstance(references, (list, tuple)) or not 2 <= len(references) <= 64:
        _invalid()
    result = {'proof': {'version': 1, 'receipts': []}, 'sources': {}, 'identities': {}}
    records, total = [], 0
    try:
        for reference in references:
            path, snapshot = _snapshot(root, reference)
            name = 'evidence/' + path.name
            if name in result['sources']:
                _invalid('BATCH_EVIDENCE_DUPLICATE')
            total += len(snapshot.content)
            if total > _MAX_TOTAL:
                _invalid('BATCH_EVIDENCE_LIMIT')
            records.append(json.loads(snapshot.content, object_pairs_hook=_pairs))
            result['sources'][name] = snapshot.content
            result['identities'][name] = [snapshot.device, snapshot.inode]
            result['proof']['receipts'].append({'ref': path.name,
                                               'sha256': 'sha256:' + hashlib.sha256(snapshot.content).hexdigest()})
        validate_finding_closure_batch(finding, records, impact, current_head=current_head,
                                      current_workspace=current_workspace)
        require_closure_sources(root, result)
        return result
    except EvidenceValidationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise EvidenceValidationError('BATCH_EVIDENCE_INVALID') from error


def require_closure_sources(root, prepared):
    try:
        root = Path(root).absolute()
        for name, expected in prepared['sources'].items():
            snapshot = source_access.read_regular_snapshot_beneath(root / name, root, max_bytes=_MAX_RECEIPT)
            if (snapshot.content != expected
                    or [snapshot.device, snapshot.inode] != prepared['identities'][name]):
                _invalid('BATCH_EVIDENCE_CHANGED')
    except EvidenceValidationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise EvidenceValidationError('BATCH_EVIDENCE_CHANGED') from error


def publish_batch_closure(root, path, finding, references, *, critical_related_approved=False):
    """Called under transition's existing owner; publish only the selected Finding."""
    from copy import deepcopy
    from datetime import UTC, datetime
    import yaml
    from jsonschema import ValidationError, validate
    from . import transaction, workspace
    from .schema_resources import read_schema
    from .transaction_recovery import _locked

    root, path = Path(root).absolute(), Path(path).absolute()
    _locked(root)
    try:
        if 'evidence' in finding and 'closure_evidence' in finding:
            _invalid('FINDING_CLOSURE_FORMAT_INVALID')
        root_identity = source_access.node_identity_beneath(root, root, node_kind='directory')['identity']
        before = source_access.read_regular_snapshot_beneath(path, root, max_bytes=_MAX_RECEIPT)
        impact_snapshot = source_access.read_regular_snapshot_beneath(root / 'impact.yaml', root, max_bytes=_MAX_RECEIPT)
        if yaml.safe_load(before.content) != finding:
            _invalid('BATCH_EVIDENCE_CHANGED')
        impact = yaml.safe_load(impact_snapshot.content)
        current = workspace.snapshot(root.parent)
        candidate = deepcopy(finding)
        if critical_related_approved:
            if finding['severity'] != 'critical':
                _invalid('CRITICAL_RELATED_APPROVAL_REQUIRED')
            candidate['closure'] = {'mode': 'related', 'critical_related_approved': True,
                                    'source': 'user', 'approved_at': datetime.now(UTC).isoformat()}
        prepared = prepare_closure_proof(root, candidate, references, impact,
                                        current_head=current.head, current_workspace=current.fingerprint)
        candidate.pop('evidence', None)
        candidate.update(status='VERIFIED', verified_at=datetime.now(UTC).isoformat(),
                         closure_evidence=prepared['proof'])
        validate(candidate, read_schema('adversarial-finding.schema.json'))
        payload = yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True).encode()
        relative_path = path.relative_to(root)
        physical_root = root.resolve()
        if (source_access.node_identity_beneath(root, root, node_kind='directory')['identity'] != root_identity
                or source_access.node_identity_beneath(physical_root, physical_root, node_kind='directory')['identity'] != root_identity):
            _invalid('BATCH_EVIDENCE_CHANGED')
        # Native stage rejects all symlink ancestors. Preserve that boundary:
        # publish through the verified physical spelling of this same root.
        root, path = physical_root, physical_root / relative_path
        artifact = transaction.StagedArtifact(relative_path.as_posix(), payload)

        def check(updated=False):
            require_closure_sources(root, prepared)
            now = source_access.read_regular_snapshot_beneath(root / 'impact.yaml', root, max_bytes=_MAX_RECEIPT)
            if (now.content != impact_snapshot.content
                    or [now.device, now.inode] != [impact_snapshot.device, impact_snapshot.inode]
                    or workspace.snapshot(root.parent) != current):
                _invalid('BATCH_EVIDENCE_CHANGED')
            actual = source_access.read_regular_snapshot_beneath(path, root, max_bytes=_MAX_RECEIPT)
            if updated:
                if actual.content != payload:
                    _invalid('BATCH_EVIDENCE_CHANGED')
            elif (actual.content != before.content or [actual.device, actual.inode] != [before.device, before.inode]):
                _invalid('BATCH_EVIDENCE_CHANGED')

        check()
        staged = transaction.stage(root, [artifact])
        check()
        transaction.publish(root, staged, replace_paths=frozenset({artifact.relative_path}), durable=True,
                            expected_sources={artifact.relative_path: before.content}, expected_artifacts=(artifact,),
                            after_publish=lambda: check(True))
    except EvidenceValidationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError, ValidationError) as error:
        raise EvidenceValidationError('BATCH_CLOSURE_INVALID') from error


def validate_persisted_batch_closure(root, finding, impact, *, current_head, current_workspace):
    if closure_proof_kind(finding) != 'batch':
        _invalid('FINDING_CLOSURE_FORMAT_INVALID')
    stored = finding['closure_evidence']
    prepared = prepare_closure_proof(root, finding, [item['ref'] for item in stored['receipts']], impact,
                                     current_head=current_head, current_workspace=current_workspace)
    if prepared['proof'] != stored:
        _invalid('BATCH_EVIDENCE_CHANGED')
    require_closure_sources(root, prepared)

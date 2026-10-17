"""Bounded FIXED proof maintenance, distinct from lifecycle transitions."""

from __future__ import annotations

import copy
import datetime
import json
import os
import re
from itertools import pairwise
from pathlib import Path

import yaml
from jsonschema import SchemaError, ValidationError

from . import (
    evidence_validator,
    publication_fs,
    quality_gate,
    source_access,
    transaction,
    workspace,
)
from .paths import EvidenceReferenceError, evidence_path
from .telemetry_lock import telemetry_lock
from .transaction_recovery import require_no_pending_publications


class FindingRefreshError(ValueError):
    """Stable refusal with no serialized proof/finding payload in error text."""


def _schema(document, name, path):
    try:
        quality_gate.validate_schema(document, name, path)
    except (quality_gate.InvalidHarnessState, ValidationError, SchemaError) as exc:
        raise FindingRefreshError('FINDING_REFRESH_SCHEMA_INVALID') from exc


def _yaml(raw):
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise FindingRefreshError('FINDING_STATE_INVALID') from exc
    if not isinstance(document, dict):
        raise FindingRefreshError('FINDING_STATE_INVALID')
    return document


def refresh_finding_proof(root: Path, fid: str, reference: str) -> bool:
    """Refresh current GREEN plus append history atomically; return False for no-op.

    Historical RED/GREEN must remain valid for same HEAD/finding/test, but are not
    reused as current proof. No task/obligation/state changes or full Gate bypass.
    """
    root = root.absolute()
    if not isinstance(fid, str) or not re.fullmatch(r'FND-[0-9]+', fid):
        raise FindingRefreshError('FINDING_ID_INVALID')
    with telemetry_lock(root):
        require_no_pending_publications(root)
        root_fd = publication_fs.open_directory(root)
        try:
            return _refresh_locked(root, root_fd, fid, reference)
        finally:
            os.close(root_fd)


def _refresh_locked(root, root_fd, fid, reference):
    inputs = {}

    def read(path):
        content = source_access.read_regular_bytes_beneath(path, root)
        if path in inputs and inputs[path] != content:
            raise FindingRefreshError('FINDING_REFRESH_SOURCE_CHANGED')
        inputs[path] = content
        return content

    def members():
        return source_access.members(root / 'findings', '*.yaml')

    namespace = members()
    selected = []
    for path in namespace:
        document = _yaml(read(path))
        if document.get('id') == fid:
            selected.append((path, document))
    if len(selected) != 1:
        raise FindingRefreshError('FINDING_ID_NOT_UNIQUE')
    path, finding = selected[0]
    if finding.get('category') != 'adversarial' or finding.get('status') != 'FIXED':
        raise FindingRefreshError('FINDING_REFRESH_REQUIRES_ADVERSARIAL_FIXED')
    _schema(finding, 'adversarial-finding.schema.json', path)
    task_path = root / 'current-task.yaml'
    task = _yaml(read(task_path))
    _schema(task, 'task.schema.json', task_path)
    task_id = task.get('task', {}).get('id')
    if (not isinstance(task_id, str) or not re.fullmatch(r'TASK-[0-9]+', task_id)
            or finding.get('task_id') != task_id):
        raise FindingRefreshError('FINDING_TASK_MISMATCH')
    regression = finding['regression_test']
    if finding.get('test') != regression['path']:
        raise FindingRefreshError('REGRESSION_TEST_MISMATCH')
    history = regression.get('green_evidence_history', [])
    if (any(left['current'] != right['previous'] for left, right in pairwise(history))
            or (history and history[-1]['current'] != regression['green_evidence'])):
        raise FindingRefreshError('FINDING_PROOF_HISTORY_INVALID')
    current = workspace.snapshot(root.parent)

    def proof(ref, success, fresh):
        try:
            resolved = evidence_path(root, ref)
        except EvidenceReferenceError as exc:
            raise FindingRefreshError('EVIDENCE_REFERENCE_INVALID') from exc
        if resolved.parent != root / 'evidence':
            raise FindingRefreshError('EVIDENCE_REFERENCE_INVALID')
        try:
            record = json.loads(read(resolved))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FindingRefreshError('EVIDENCE_SCHEMA_INVALID') from exc
        evidence_validator.validate_evidence(
            record, current_head=current.head, current_workspace=current.fingerprint,
            expected_success=success, finding_id=fid, test_id=regression['path'],
            require_current_workspace=fresh,
        )
        if any(key in record and record[key] != task_id for key in ('task', 'task_id')):
            raise FindingRefreshError('FINDING_TASK_MISMATCH')
        return resolved

    proof(regression['red_evidence'], False, False)
    old = proof(regression['green_evidence'], True, False)
    historical = {entry[key] for entry in history for key in ('previous', 'current')}
    for ref in sorted(historical - {regression['green_evidence']}):
        proof(ref, True, False)
    new = proof(reference, True, True)

    def check(updated=None):
        opened = publication_fs.open_directory(root)
        try:
            named, pinned = os.fstat(opened), os.fstat(root_fd)
            if (named.st_dev, named.st_ino) != (pinned.st_dev, pinned.st_ino):
                raise FindingRefreshError('FINDING_REFRESH_SOURCE_CHANGED')
        finally:
            os.close(opened)
        if members() != namespace or workspace.snapshot(root.parent) != current:
            raise FindingRefreshError('FINDING_REFRESH_SOURCE_CHANGED')
        for source, content in inputs.items():
            expected = updated if source == path and updated is not None else content
            if source_access.read_regular_bytes_beneath(source, root) != expected:
                raise FindingRefreshError('FINDING_REFRESH_SOURCE_CHANGED')

    check()
    if old == new:
        return False
    updated = copy.deepcopy(finding)
    updated['regression_test']['green_evidence'] = new.name
    updated['regression_test'].setdefault('green_evidence_history', []).append({
        'previous': regression['green_evidence'], 'current': new.name,
        'refreshed_at': datetime.datetime.now(datetime.UTC).isoformat(),
    })
    _schema(updated, 'adversarial-finding.schema.json', path)
    payload = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True).encode()
    artifact = transaction.StagedArtifact(path.relative_to(root).as_posix(), payload)
    staged = transaction.stage(root, [artifact])
    check()
    transaction.publish(root, staged, replace_paths=frozenset({artifact.relative_path}),
                        expected_sources={artifact.relative_path: inputs[path]}, expected_artifacts=(artifact,),
                        after_publish=lambda: check(payload), durable=True)
    return True

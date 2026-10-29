"""Opt-in v2 advice; independent tool facts never authorize product execution."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .context.model import ContextBuildError
from .evidence_plan import _plan_from_sources, diagnostic_sources
from .execution_capture import supported_command
from .launcher_probe import probe_launcher
from .tool_identity import begin_tool_identity, finish_tool_identity

DRIFT_CODES = frozenset({'CONTRACT_CHANGED', 'SCOPE_DRIFT_API', 'SCOPE_DRIFT_PERMISSION', 'SCOPE_DRIFT_PERSISTENCE'})
SCOPE_CODES = frozenset({'TEST_SCOPE_AUDIT_INVALID', 'TEST_SCOPE_RETIREMENT_UNAUDITED', 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'})
GATE_INTEGRITY_CODES = DRIFT_CODES | SCOPE_CODES
SOURCE_BLOCKED_CODES = frozenset({'TRANSACTION_RECOVERY_REQUIRED', 'TRANSACTION_RECOVERY_BLOCKED', 'CONTEXT_STALE'})
CONSTRAINTS = ('PRESERVE_OBLIGATIONS', 'PRESERVE_RISK', 'NO_EXECUTION', 'NO_RELEASE')


@dataclass(frozen=True)
class PreflightRequest:
    probe_cwd: Path
    commands: tuple[str, ...] = ()
    skills_package: Path | None = None
    probe_launcher: Path | None = None


def classify_commands(commands: tuple[object, ...]) -> dict:
    rows, seen = [], set()
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            rows.append({'command': command if isinstance(command, str) else None,
                         'status': 'UNKNOWN', 'reason_code': 'INVALID_COMMAND_INPUT'})
            continue
        if command in seen:
            continue
        seen.add(command)
        supported = supported_command(command)
        rows.append({'command': command,
                     'status': 'NATIVE_PROFILE_SUPPORTED' if supported else 'MEASUREMENT_ONLY',
                     'reason_code': 'QUALIFIED_BY_SUPPORTED_COMMAND' if supported else 'REJECTED_BY_SUPPORTED_COMMAND'})
    statuses = {row['status'] for row in rows}
    status = ('NOT_REQUESTED' if not rows else 'INVALID_REQUEST' if 'UNKNOWN' in statuses
              else 'BLOCKED' if 'MEASUREMENT_ONLY' in statuses else 'SUPPORTED')
    return {'status': status, 'commands': rows}


def _diagnostic(code: str, component: str, source_ref: str | None = None) -> dict:
    return {'code': code, 'component': component, 'source_ref': source_ref,
            'message': 'Diagnosis is advisory; follow the existing authority and recovery policy.'}


def repair_requirements(codes: tuple[str, ...], *, source=None, source_versions: dict | None) -> list[dict]:
    rows = []
    for code in dict.fromkeys(codes):
        if code not in GATE_INTEGRITY_CODES:
            continue
        drift = code in DRIFT_CODES
        rows.append({'code': code,
                     'operation': 'ALIGN_REVISE' if drift else 'INSPECT_SCOPE_AUTHORITY',
                     'authority': 'USER_CONTRACT_REVISION' if drift else 'USER_INSPECTION_REQUIRED',
                     'task_id': None, 'source_refs': None, 'scope': None,
                     'constraints': list(CONSTRAINTS)})
    # Every emitted operation here describes an integrity failure. None can
    # certify the failed B inputs or manufacture a historical source/hash.
    return rows


def _source_failure(exc: Exception) -> tuple[str, list[str]]:
    if isinstance(exc, ContextBuildError):
        codes = exc.drift_codes
        if (exc.code == 'CONTEXT_SCHEMA_INVALID' and isinstance(codes, tuple) and codes
                and all(isinstance(code, str) and code in DRIFT_CODES for code in codes)):
            return 'BLOCKED', list(dict.fromkeys(codes))
        return ('BLOCKED' if exc.code in SOURCE_BLOCKED_CODES else 'INVALID'), [exc.code]
    return 'INVALID', ['INVALID_HARNESS_STATE']


def _empty_product() -> dict:
    return {'status': 'NOT_EVALUATED', 'diagnostics': [], 'execution_plan': None}


def _tool_failure(request: PreflightRequest) -> dict:
    return {'cli_identity': {'status': 'INVALID', 'verified_version': None},
            'schema_identity': {'status': 'INVALID', 'versions': None, 'sha256': None},
            'skills_identity': {'status': 'NOT_PROVIDED' if request.skills_package is None else 'UNVERIFIABLE',
                                'path': str(request.skills_package) if request.skills_package else None,
                                'version': None, 'sha256': None},
            'diagnostics': [], 'errors': [{'code': 'TOOL_IDENTITY_ERROR', 'component': 'tooling'}]}


def run_preflight(harness_dir: Path, request: PreflightRequest) -> dict:
    commands = classify_commands(request.commands)
    probe = {'status': 'NOT_REQUESTED', 'spawn_attempts': 0}
    tools = None
    snapshot = None
    tool_started = False
    tool_finished = False
    try:
        snapshot = begin_tool_identity(request.skills_package)
        tool_started = True
    except Exception:  # noqa: BLE001 - v2 JSON boundary, never leak tool exceptions
        tools = _tool_failure(request)
    integrity = {'status': 'INVALID', 'diagnostics': []}
    product = _empty_product()
    hints = []
    task_id, source_versions = None, None
    errors = []
    probe_finished = False

    def finish_a():
        nonlocal probe, tools, probe_finished, tool_finished
        if not probe_finished:
            probe_finished = True
            if request.probe_launcher is not None:
                try:
                    probe = probe_launcher(request.probe_launcher, cwd=request.probe_cwd)
                except Exception:  # noqa: BLE001 - internal probe failure is never success
                    probe = {'status': 'CLEANUP_ERROR', 'spawn_attempts': 0}
        if not tool_finished:
            tool_finished = True
            if tool_started:
                try:
                    tools = finish_tool_identity(snapshot)
                except Exception:  # noqa: BLE001 - preserve JSON on tool-provider faults
                    tools = _tool_failure(request)

    try:
        with diagnostic_sources(harness_dir) as (source, before, versions):
            codes = tuple(blocker.code for blocker in source.gate.blockers
                          if blocker.code in GATE_INTEGRITY_CODES)
            if codes:
                integrity = {'status': 'BLOCKED', 'diagnostics': [_diagnostic(code, 'integrity') for code in dict.fromkeys(codes)]}
                hints = repair_requirements(codes, source=None, source_versions=None)
                # No product traversal or in-lock A execution on failed inputs.
            else:
                integrity = {'status': 'VALID', 'diagnostics': []}
                planned = _plan_from_sources(harness_dir, source, before, versions)
                diagnostics = list(planned['diagnostics'])
                diagnostics.extend(_diagnostic(blocker.code, 'product', blocker.source)
                                   for blocker in source.gate.blockers)
                product = {'status': 'GAPS' if diagnostics or source.gate.status != 'PASS' else 'NO_GAPS',
                           'diagnostics': diagnostics, 'execution_plan': planned['execution_plan']}
                task_id, source_versions = planned['task_id'], before
                finish_a()  # same telemetry lock, before the existing final freshness
    except Exception as exc:  # noqa: BLE001 - source failure must discard all B facts
        state, codes = _source_failure(exc)
        integrity = {'status': state, 'diagnostics': [_diagnostic(code, 'integrity') for code in codes]}
        task_id, source_versions, product = None, None, _empty_product()
        hints = [] if 'CONTEXT_STALE' in codes else repair_requirements(tuple(codes), source=None, source_versions=None)
        if state == 'INVALID':
            errors.append({'code': codes[0], 'component': 'integrity'})
    finish_a()  # only if admission failed; never reenter product Context
    if tools['schema_identity']['status'] == 'CHANGED':
        integrity = {'status': 'BLOCKED', 'diagnostics': [_diagnostic('CONTEXT_STALE', 'integrity')]}
        task_id, source_versions, product, hints = None, None, _empty_product(), []
    tooling = {key: value for key, value in tools.items() if key != 'errors'}
    tooling['launcher_probe'] = probe
    errors.extend(tools['errors'])
    if probe['status'] not in {'NOT_REQUESTED', 'SUCCEEDED'}:
        tooling['diagnostics'].append(_diagnostic('PROBE_' + probe['status'], 'launcher_probe'))
    tool_error = bool(tools['errors']) or probe['status'] == 'CLEANUP_ERROR'
    tool_blocked = (tools['cli_identity']['status'] != 'VERIFIED'
                    or tools['schema_identity']['status'] != 'VERIFIED'
                    or tools['skills_identity']['status'] not in {'NOT_PROVIDED', 'MATCH'}
                    or probe['status'] not in {'NOT_REQUESTED', 'SUCCEEDED'})
    optional_missing = tools['skills_identity']['status'] == 'NOT_PROVIDED' or probe['status'] == 'NOT_REQUESTED'
    tooling['status'] = ('ERROR' if tool_error else 'BLOCKED' if tool_blocked
                         else 'NOT_VERIFIED' if optional_missing else 'READY')
    command_value = {'NOT_REQUESTED': 0, 'SUPPORTED': 0, 'BLOCKED': 1, 'INVALID_REQUEST': 2}[commands['status']]
    if tool_error or tool_blocked or command_value:
        product['execution_plan'] = None
    exit_code = max(2 if errors or tool_error or integrity['status'] == 'INVALID' else 0,
                    1 if integrity['status'] == 'BLOCKED' or tool_blocked or product['status'] == 'GAPS' else 0,
                    command_value)
    return {'version': 2, 'advisory': True, 'execution_authority': False,
            'outcome': ('CLEAR', 'BLOCKED', 'ERROR')[exit_code], 'exit_code': exit_code,
            'task_id': task_id, 'source_versions': source_versions, 'integrity': integrity,
            'tooling': tooling, 'execution_capabilities': commands, 'product': product,
            'repair_requirements': hints, 'execution_counts': {'tests': 0, 'business': 0,
                                                             'environment': probe['spawn_attempts']},
            'errors': errors}

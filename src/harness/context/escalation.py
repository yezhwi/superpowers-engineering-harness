"""Task-bound expansion authority; breadth is independent of execution authority."""

import re
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

import yaml

from harness import transaction
from harness.telemetry_lock import telemetry_lock

from .freshness import capture, digest, require_fresh
from .model import AuthoritativeContext, ContextBuildError
from .policy import policy_for_risk
from .telemetry import increment, instrument

REPORTED_TRIGGERS = (
    "SYMBOL_UNRESOLVED",
    "REQUIREMENT_UNMAPPED",
    "CROSS_MODULE_DEPENDENCY",
    "API_OR_CONFIG_CHANGE",
    "INSUFFICIENT_CONTEXT",
)
AUTOMATIC_TRIGGERS = (
    "FINDING_OUTSIDE_SCOPE",
    "DECISION_OUTSIDE_SCOPE",
    "TEST_FAILURE_OUTSIDE_WORKING_SET",
    "RISK_ESCALATED",
)
FAIL_CLOSED_TRIGGERS = ("CONTEXT_INTEGRITY_UNPROVEN",)
ORDER = ("LOCAL", "BOUNDED", "EXPANDED")


def automatic_candidates(context: dict) -> list[dict]:
    """Finite declared paths only. Fingerprints exclude counters and log output."""
    from .selector import path_is_owned

    owners = (context["control"]["scope"] or {}).get("owned_paths", [])
    candidates = []
    risk = context["control"]["task"]["risk"]
    levels = {"Q1": 0, "Q2": 1, "Q3": 2}
    previous = -1
    for index, entry in enumerate(risk.get("escalation_history", [])):
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("from"), str)
            or not isinstance(entry.get("to"), str)
            or entry.get("from") not in levels
            or entry.get("to") not in levels
            or levels[entry["from"]] >= levels[entry["to"]]
            or levels[entry["from"]] < previous
            or levels[entry["to"]] > levels[risk["level"]]
            or not isinstance(entry.get("reason"), str)
            or not entry["reason"].strip()
        ):
            raise ContextBuildError(
                "CONTEXT_POLICY_MISMATCH", "invalid risk escalation history"
            )
        previous = levels[entry["to"]]
        candidates.append(
            {
                "trigger": "RISK_ESCALATED",
                "object_id": f"risk:{index}",
                "source_hash": digest(entry),
                "reason": entry["reason"],
            }
        )
    for evidence in context["control"]["evidence"]:
        missing = sorted(
            set(evidence.get("covered_tests", [])) - set(context["working"]["tests"])
        )
        if evidence["exit_code"] != 0 and missing:
            candidates.append(
                {
                    "trigger": "TEST_FAILURE_OUTSIDE_WORKING_SET",
                    "object_id": evidence["ref"],
                    "source_hash": digest(
                        {
                            "exit_code": evidence["exit_code"],
                            "covered_tests": sorted(set(evidence["covered_tests"])),
                            "owners": sorted(set(owners)),
                        }
                    ),
                    "reason": "Failed evidence covers tests absent from Working Set",
                }
            )
    for group, trigger in (
        ("findings", "FINDING_OUTSIDE_SCOPE"),
        ("decisions", "DECISION_OUTSIDE_SCOPE"),
    ):
        for record in context["control"][group]:
            paths = (
                record.get("scope", [])
                if group == "decisions"
                else [
                    path
                    for path in (
                        record.get("location", {}).get("file"),
                        record.get("regression_test", {}).get("path"),
                    )
                    if path
                ]
            )
            outside = (
                (
                    bool(paths)
                    and not any(
                        path_is_owned(path, owners)
                        or any(path_is_owned(owner, [path]) for owner in owners)
                        for path in paths
                    )
                )
                if group == "decisions"
                else any(not path_is_owned(path, owners) for path in paths)
            )
            if outside:
                candidates.append(
                    {
                        "trigger": trigger,
                        "object_id": record["id"],
                        "source_hash": digest(
                            {"paths": sorted(set(paths)), "owners": sorted(set(owners))}
                        ),
                        "reason": f"{record['id']} declares paths outside owned scope",
                    }
                )
    return candidates


@dataclass(frozen=True)
class ExpansionBatch:
    task_id: str
    original_versions: dict
    original_tail_digest: str | None
    events: tuple[dict, ...]
    budget_delta: int
    final_policy: str


@instrument('expansion_plan')
def plan_automatic_expansions(
    validated_source: AuthoritativeContext, current_context: dict,
) -> ExpansionBatch:
    from .integrity import _project_context

    source = deepcopy(validated_source)
    context = current_context
    candidates = automatic_candidates(context)  # one initial ordered boundary
    increment('expansion_candidates', len(candidates))
    planned = []
    task_id = source.task['task']['id']
    if task_id != context['control']['task']['id']:
        raise ContextBuildError('CONTEXT_POLICY_MISMATCH', 'batch task mismatch')
    harness_dir = Path.cwd() / Path(source.references['current-task.yaml']['ref']).parent
    for candidate in candidates:
        if any(all(event.get(field) == candidate[field] for field in
                   ('trigger', 'object_id', 'source_hash')) for event in context['expansions']):
            continue
        if candidate not in automatic_candidates(context):
            break  # legal prefix commits; do not visit any later initial candidate
        event = _make_expansion_event(source.task, context, candidate['trigger'], candidate['reason'], candidate)
        planned.append(event)
        source.task['budget']['context_expansions'] = source.task['budget'].get('context_expansions', 0) + 1
        events = source.expansions + [event]
        active_expansions(source.task, {'expansions': events})
        source = replace(source, expansions=events)
        context = _project_context(harness_dir, source, current_context['generated_from'], mode=context['mode'])
    versions = current_context['generated_from']
    return ExpansionBatch(task_id, deepcopy(versions), versions['files'].get('context/expansions.yaml'),
                          tuple(planned), len(planned), context['policy'])


def publish_expansion_batch(harness_dir: Path, batch: ExpansionBatch, expected_sources: dict, *, workspace=None) -> dict:
    if batch.original_versions != expected_sources or batch.budget_delta != len(batch.events):
        raise ContextBuildError('CONTEXT_POLICY_MISMATCH', 'invalid expansion batch')
    if any(event['task_id'] != batch.task_id for event in batch.events):
        raise ContextBuildError('CONTEXT_POLICY_MISMATCH', 'batch event task mismatch')
    if batch.original_tail_digest != expected_sources['files'].get('context/expansions.yaml'):
        raise ContextBuildError('CONTEXT_STALE', 'expansion log basis changed')
    if batch.events:
        _publish_expansion_events(
            harness_dir, expected_sources, list(batch.events),
            final_policy=batch.final_policy, workspace=workspace,
        )
    return {'events': list(batch.events), 'policy': batch.final_policy}


def apply_automatic_expansions(
    harness_dir: Path, context: dict, *, source: AuthoritativeContext, workspace=None,
) -> dict:
    from .integrity import build_context

    batch = plan_automatic_expansions(source, context)
    if not batch.events:
        return context
    publish_expansion_batch(
        harness_dir, batch, context['generated_from'], workspace=workspace,
    )
    return build_context(harness_dir, mode=context['mode'], workspace=workspace)


def active_expansions(task: dict, document: dict | None) -> list[dict]:
    events = [] if document is None else document.get("expansions")
    if not isinstance(events, list) or (
        document is not None and set(document) != {"expansions"}
    ):
        raise ContextBuildError("CONTEXT_POLICY_MISMATCH", "invalid expansion log")
    active = []
    previous = 0
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            raise ContextBuildError(
                "CONTEXT_POLICY_MISMATCH", "invalid expansion event"
            )
        automatic = event.get("trigger") in AUTOMATIC_TRIGGERS
        if set(event) != (
            {
                "task_id",
                "source_hash",
                "from",
                "to",
                "trigger",
                "reason",
            }
            | ({"object_id"} if automatic else set())
        ):
            raise ContextBuildError(
                "CONTEXT_POLICY_MISMATCH", "invalid expansion event"
            )
        if (
            not all(isinstance(value, str) for value in event.values())
            or not event["task_id"].strip()
            or not event["reason"].strip()
            or event["trigger"] not in REPORTED_TRIGGERS + AUTOMATIC_TRIGGERS
            or (automatic and not event["object_id"].strip())
            or event["from"] not in ORDER
            or event["to"] not in ORDER
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", event["source_hash"])
        ):
            raise ContextBuildError(
                "CONTEXT_POLICY_MISMATCH", "invalid expansion authority"
            )
        if automatic:
            identity = tuple(
                event[key] for key in ("task_id", "trigger", "object_id", "source_hash")
            )
            if identity in seen:
                raise ContextBuildError(
                    "CONTEXT_POLICY_MISMATCH", "duplicate automatic expansion"
                )
            seen.add(identity)
        start, end = ORDER.index(event["from"]), ORDER.index(event["to"])
        if (
            end < start
            if event["trigger"] == "RISK_ESCALATED"
            else end != min(start + 1, 2)
        ):
            raise ContextBuildError("CONTEXT_POLICY_MISMATCH", "invalid expansion step")
        if event["task_id"] == task["task"]["id"]:
            if start < previous:
                raise ContextBuildError(
                    "CONTEXT_POLICY_MISMATCH", "expansion policy decreased"
                )
            previous = end
            active.append(event)
    if task.get("budget", {}).get("context_expansions", 0) != len(active):
        raise ContextBuildError(
            "CONTEXT_POLICY_MISMATCH", "expansion budget/log mismatch"
        )
    return deepcopy(active)


def effective_policy(task: dict, events: list[dict]) -> str:
    base = ORDER.index(policy_for_risk(task["risk"]))
    return ORDER[max([base, *(ORDER.index(event["to"]) for event in events)])]


def expand_context(harness_dir: Path, trigger: str, reason: str) -> dict:
    """Persist event and counter together. Leave old derived Context stale."""

    if (
        trigger not in REPORTED_TRIGGERS
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise ContextBuildError(
            "CONTEXT_SCHEMA_INVALID",
            "valid reported trigger and nonblank reason required",
        )
    return _record_expansion(harness_dir, trigger, reason)


def _make_expansion_event(task: dict, context: dict, trigger: str, reason: str, automatic: dict | None) -> dict:
    policy = context['policy']
    event = {
        'task_id': task['task']['id'], 'source_hash': digest(context['generated_from']),
        'from': policy, 'to': ORDER[min(ORDER.index(policy) + 1, 2)],
        'trigger': trigger, 'reason': reason.strip(),
    }
    if automatic is not None:
        event.update(automatic)  # candidate source_hash overrides generated_from
        if trigger == 'RISK_ESCALATED':
            index = int(automatic['object_id'].split(':')[1])
            history = task['risk']['escalation_history'][index]
            start = max([int(history['from'][1]) - 1,
                         *(ORDER.index(item['to']) for item in context['expansions'])])
            event['from'] = ORDER[start]
            event['to'] = ORDER[max(start, ORDER.index(policy))]
    return event


def _publish_expansion_events(
    harness_dir: Path, versions: dict, events: list[dict], *,
    final_policy: str | None = None, workspace=None,
):
    import hashlib

    from harness import source_access

    from .store import _paths

    harness_dir = harness_dir.absolute()
    with telemetry_lock(harness_dir):
        transaction.recover_pending_publications(harness_dir)
        _paths(harness_dir)
        task_path = harness_dir / 'current-task.yaml'
        log_path = harness_dir / 'context/expansions.yaml'
        staging_root = harness_dir / '.staging'
        if any(path.is_symlink() for path in (task_path, log_path, staging_root)):
            raise ContextBuildError('CONTEXT_REFERENCE_BROKEN', 'expansion storage cannot be a symlink')
        require_fresh(versions, capture(harness_dir, workspace=workspace))
        task_bytes = source_access.read_regular_bytes_beneath(task_path, harness_dir)
        old_log = source_access.read_regular_bytes_beneath(log_path, harness_dir) if log_path.exists() else None
        for name, content in (('current-task.yaml', task_bytes), ('context/expansions.yaml', old_log)):
            observed = None if content is None else 'sha256:' + hashlib.sha256(content).hexdigest()
            if observed != versions['files'].get(name):
                raise ContextBuildError('CONTEXT_STALE', 'expansion input bytes changed')
        task = yaml.safe_load(task_bytes)
        historical = [] if old_log is None else yaml.safe_load(old_log)['expansions']
        if any(event['task_id'] != task['task']['id'] for event in events):
            raise ContextBuildError('CONTEXT_POLICY_MISMATCH', 'event task mismatch')
        task['budget']['context_expansions'] = task['budget'].get('context_expansions', 0) + len(events)
        log = {'expansions': historical + events}
        active = active_expansions(task, log)
        if final_policy is not None and effective_policy(task, active) != final_policy:
            raise ContextBuildError('CONTEXT_POLICY_MISMATCH', 'batch policy mismatch')
        payloads = {
            'current-task.yaml': yaml.safe_dump(task, sort_keys=False).encode(),
            'context/expansions.yaml': yaml.safe_dump(log, sort_keys=False).encode(),
        }
        before = {'current-task.yaml': task_bytes, 'context/expansions.yaml': old_log}
        expected = deepcopy(versions)
        for name, value in payloads.items():
            version = 'sha256:' + hashlib.sha256(value).hexdigest()
            expected['files'][name] = version
            declared = f'{harness_dir.name}/{name}'
            if declared in expected['declared_files']:
                expected['declared_files'][declared] = version
        expected['control_plane_hash'] = digest(expected['files'])
        expected['task_hash'] = digest({'current-task.yaml': expected['files']['current-task.yaml']})
        def finalize():
            require_fresh(expected, capture(harness_dir, workspace=workspace))
            require_fresh(expected, capture(harness_dir, workspace=workspace))

        artifacts = tuple(transaction.StagedArtifact(n, b) for n, b in payloads.items())
        staged = transaction.stage(harness_dir, artifacts, operation_id=f'context-expand-{uuid4().hex}')
        require_fresh(versions, capture(harness_dir, workspace=workspace))
        transaction.publish(harness_dir, staged, replace_paths=frozenset(payloads),
                            after_publish=finalize, durable=True,
                            expected_sources=before, expected_artifacts=artifacts)
        increment('expansion_events_written', len(events))


def _record_expansion(
    harness_dir: Path, trigger: str, reason: str, *, automatic: dict | None = None, mode: str = 'full',
) -> dict:
    from .integrity import build_context
    from .store import _paths

    harness_dir = harness_dir.absolute()
    with telemetry_lock(harness_dir):
        transaction.recover_pending_publications(harness_dir)
        _paths(harness_dir)
        context = build_context(harness_dir, mode=mode)
        if automatic is not None:
            if automatic not in automatic_candidates(context):
                raise ContextBuildError('CONTEXT_STALE', 'automatic trigger basis changed')
            for existing in context['expansions']:
                if all(existing.get(key) == automatic[key] for key in ('trigger', 'object_id', 'source_hash')):
                    return existing
        task = yaml.safe_load((harness_dir / 'current-task.yaml').read_bytes())
        event = _make_expansion_event(task, context, trigger, reason, automatic)
        _publish_expansion_events(harness_dir, context['generated_from'], [event])
        return event

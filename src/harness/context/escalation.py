"""Task-bound expansion authority; breadth is independent of execution authority."""

import re
import shutil
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import yaml

from harness import transaction
from harness.telemetry_lock import telemetry_lock

from .freshness import capture, digest, require_fresh
from .model import ContextBuildError
from .policy import policy_for_risk

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


def apply_automatic_expansions(harness_dir: Path, context: dict) -> dict:
    """Write each new event before rebuilding; no repeated upgrade from same basis."""
    from .integrity import build_context

    for candidate in automatic_candidates(context):
        key = lambda event: tuple(
            event.get(field) for field in ("trigger", "object_id", "source_hash")
        )
        if any(key(event) == key(candidate) for event in context["expansions"]):
            continue
        _record_expansion(
            harness_dir,
            candidate["trigger"],
            candidate["reason"],
            automatic=candidate,
            mode=context["mode"],
        )
        context = build_context(harness_dir, mode=context["mode"])
    return context


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


def _record_expansion(
    harness_dir: Path,
    trigger: str,
    reason: str,
    *,
    automatic: dict | None = None,
    mode: str = "full",
) -> dict:
    from .integrity import build_context
    from .store import _paths, _restore

    harness_dir = harness_dir.absolute()
    with telemetry_lock(harness_dir):
        _paths(harness_dir)
        task_path = harness_dir / "current-task.yaml"
        log_path = harness_dir / "context/expansions.yaml"
        staging_root = harness_dir / ".staging"
        if any(path.is_symlink() for path in (task_path, log_path, staging_root)):
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", "expansion storage cannot be a symlink"
            )
        context = build_context(harness_dir, mode=mode)
        if automatic is not None:
            if automatic not in automatic_candidates(context):
                raise ContextBuildError(
                    "CONTEXT_STALE", "automatic trigger basis changed"
                )
            for existing in context["expansions"]:
                if all(
                    existing.get(key) == automatic[key]
                    for key in ("trigger", "object_id", "source_hash")
                ):
                    return existing
        task_bytes = task_path.read_bytes()
        task = yaml.safe_load(task_bytes)
        old_log = log_path.read_bytes() if log_path.exists() else None
        events = [] if old_log is None else yaml.safe_load(old_log)["expansions"]
        policy = context["policy"]
        event = {
            "task_id": task["task"]["id"],
            "source_hash": digest(context["generated_from"]),
            "from": policy,
            "to": ORDER[min(ORDER.index(policy) + 1, 2)],
            "trigger": trigger,
            "reason": reason.strip(),
        }
        if automatic is not None:
            event.update(automatic)
            if trigger == "RISK_ESCALATED":
                index = int(automatic["object_id"].split(":")[1])
                history = task["risk"]["escalation_history"][index]
                start = max(
                    [
                        int(history["from"][1]) - 1,
                        *(ORDER.index(item["to"]) for item in context["expansions"]),
                    ]
                )
                event["from"] = ORDER[start]
                event["to"] = ORDER[max(start, ORDER.index(policy))]
        task["budget"]["context_expansions"] = (
            task["budget"].get("context_expansions", 0) + 1
        )
        log = {"expansions": events + [event]}
        active_expansions(task, log)
        payloads = {
            "current-task.yaml": yaml.safe_dump(task, sort_keys=False).encode(),
            "context/expansions.yaml": yaml.safe_dump(log, sort_keys=False).encode(),
        }
        paths = {"current-task.yaml": task_path, "context/expansions.yaml": log_path}
        before = {"current-task.yaml": task_bytes, "context/expansions.yaml": old_log}
        operation = f"context-expand-{uuid4().hex}"
        staged = staging_root / operation
        publishing = False
        try:
            transaction.stage(
                harness_dir,
                [
                    transaction.StagedArtifact(name, value)
                    for name, value in payloads.items()
                ],
                operation_id=operation,
            )
            require_fresh(context["generated_from"], capture(harness_dir))
            publishing = True
            transaction.publish(harness_dir, staged, replace_paths=frozenset(payloads))
            expected = deepcopy(context["generated_from"])
            import hashlib

            for name, value in payloads.items():
                version = "sha256:" + hashlib.sha256(value).hexdigest()
                expected["files"][name] = version
                declared = f"{harness_dir.name}/{name}"
                if declared in expected["declared_files"]:
                    expected["declared_files"][declared] = version
            expected["control_plane_hash"] = digest(expected["files"])
            expected["task_hash"] = digest(
                {"current-task.yaml": expected["files"]["current-task.yaml"]}
            )
            require_fresh(expected, capture(harness_dir))
        except BaseException:
            _paths(harness_dir)
            if any(path.is_symlink() for path in paths.values()):
                raise ContextBuildError(
                    "CONTEXT_REFERENCE_BROKEN", "expansion storage changed"
                )
            if publishing:
                # Roll back only bytes this operation wrote; never undo an
                # unmanaged edit discovered by the post-publication hash check.
                owned = {
                    name: path
                    for name, path in paths.items()
                    if path.exists() and path.read_bytes() == payloads[name]
                }
                _restore(owned, before)
            raise
        finally:
            shutil.rmtree(staged, ignore_errors=True)
        return event

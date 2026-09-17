"""Deterministic Working Set selection over explicitly declared candidates only."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Protocol

from harness.quality_gate import OPEN_FINDING_STATUSES

from .builder import cross_task_decision_ids
from .escalation import effective_policy
from .model import AuthoritativeContext, ContextBuildError
from .policy import next_action


@dataclass(frozen=True)
class ContextSelection:
    working: dict
    omitted: list[dict]


class ContextSelector(Protocol):
    def select(
        self, source: AuthoritativeContext, policy: str, *, mode: str = "compact"
    ) -> ContextSelection: ...


def _parts(value: str) -> tuple[str, ...]:
    filename = value.split("::", 1)[0]
    path = PurePosixPath(filename)
    if (
        not filename
        or path.is_absolute()
        or PureWindowsPath(filename).drive
        or ".." in path.parts
        or "\\" in filename
    ):
        raise ContextBuildError("CONTEXT_REFERENCE_BROKEN", "noncanonical working path")
    return path.parts


def path_is_owned(path: str, owners: list[str]) -> bool:
    parts = _parts(path)
    for owner in owners:
        prefix = _parts(owner.removesuffix("/**"))
        if any(any(char in segment for char in "*?[") for segment in prefix):
            continue  # no general glob matching or repository scan
        if parts[: len(prefix)] == prefix:
            return True
    return False


def _broad(path: str) -> bool:
    parts = _parts(path.removesuffix("/**"))
    return (
        not parts
        or parts in {("docs",), ("tests",), ("test",)}
        or any(any(char in segment for char in "*?[") for segment in parts)
    )


def _strings(document: dict, key: str) -> list[str]:
    values = document.get(key, [])
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise ContextBuildError("CONTEXT_SCHEMA_INVALID", f"invalid path list: {key}")
    return values


class DeterministicSelector:
    def select(
        self, source: AuthoritativeContext, policy: str, *, mode: str = "compact"
    ) -> ContextSelection:
        if policy != effective_policy(source.task, source.expansions):
            raise ContextBuildError(
                "CONTEXT_POLICY_MISMATCH",
                "context expansion requires persisted authority",
            )
        if mode not in {"full", "compact"}:
            raise ContextBuildError("CONTEXT_SCHEMA_INVALID", "unknown context mode")
        full = mode == "full"
        scope = source.task.get("scope") or {}
        owners = _strings(scope, "owned_paths")
        # A broad ownership declaration remains in Control Core, but must not
        # make all optional requirements relevant to LOCAL's default view.
        binding_owners = [p for p in owners if policy != "LOCAL" or not _broad(p)]
        open_findings = [
            r for r in source.findings if r["status"] in OPEN_FINDING_STATUSES
        ]
        targets = {r.get("target") for r in open_findings}
        working = {
            "requirements": [],
            "decisions": [],
            "findings": [],
            "files": [],
            "tests": [],
            "goal": {
                "title": source.task["task"].get("title"),
                "description": source.task["task"].get("description"),
            },
            "next_action": next_action(
                source.task["state"], source.task["risk"]["profile"]
            ),
        }
        omitted = []

        def omit(identifier: str, name: str, reason: str, fragment: str | None = None):
            ref = source.references[name]
            if ref is None:
                raise ContextBuildError(
                    "CONTEXT_REFERENCE_BROKEN", f"missing declaration: {name}"
                )
            omitted.append(
                {
                    "id": identifier,
                    "reason": reason,
                    **ref,
                    "ref": ref["ref"] + (f"#{fragment}" if fragment else ""),
                }
            )

        for record in source.requirements:
            if record["priority"] == "must":
                continue
            tests = [
                test
                for case in record.get("test_plan", {}).get("cases", [])
                for test in case.get("tests", [])
            ]
            relevant = record["id"] in targets or any(
                path_is_owned(test, binding_owners) for test in tests
            )
            if full or relevant:
                working["requirements"].append(record)
            else:
                omit(
                    record["id"],
                    "requirements.yaml",
                    "unrelated_to_scope",
                    record["id"],
                )
        task_id = source.task["task"]["id"]
        referenced_decisions = cross_task_decision_ids(source.decisions, task_id)
        known_decisions = {record["id"] for record in source.decisions}
        missing = sorted(referenced_decisions - known_decisions)
        if missing:
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN",
                f"missing declaration: decisions/{missing[0]}.yaml",
            )
        for group, records, global_status in (
            ("decisions", source.decisions, {"ACCEPTED"}),
            ("findings", source.findings, OPEN_FINDING_STATUSES),
        ):
            for record in records:
                if group == "decisions" and record.get("task_id") != task_id:
                    if record["id"] in referenced_decisions:
                        omit(
                            record["id"],
                            f"decisions/{record['id']}.yaml",
                            "cross_task_reference",
                            record["id"],
                        )
                    elif record["status"] == "ACCEPTED":
                        omit(
                            record["id"],
                            f"decisions/{record['id']}.yaml",
                            "different_task_not_referenced",
                            record["id"],
                        )
                    elif full:
                        working[group].append(record)
                    else:
                        omit(
                            record["id"],
                            f"decisions/{record['id']}.yaml",
                            "non_global_record",
                            record["id"],
                        )
                    continue
                if record["status"] in global_status:
                    continue
                if full:
                    working[group].append(record)
                else:
                    omit(
                        record["id"],
                        f"{group}/{record['id']}.yaml",
                        "non_global_record",
                        record["id"],
                    )

        loaded_decision_ids = {record["id"] for record in source.decisions}
        for record in source.decision_metadata:
            if (
                record["id"] not in loaded_decision_ids
                and record["task_id"] != task_id
                and record["status"] == "ACCEPTED"
            ):
                omit(
                    record["id"],
                    "decisions/index.yaml",
                    "different_task_not_referenced",
                    record["id"],
                )

        candidates: dict[str, dict[str, tuple[str, bool]]] = {"files": {}, "tests": {}}

        def add(group: str, paths: list[str], name: str, allowed: bool = True):
            for path in paths:
                _parts(path)
                previous = candidates[group].get(path)
                if previous is None or allowed:
                    candidates[group][path] = (name, allowed)

        add("files", owners, "current-task.yaml")
        # Protected-only user files are visible globally, never silently owned.
        add(
            "files", _strings(scope, "protected_user_paths"), "current-task.yaml", False
        )
        impact = (source.impact or {}).get("impact", {})
        add("files", _strings(impact, "changed"), "impact.yaml")
        add("tests", _strings(impact, "required_tests"), "impact.yaml")
        for key in ("direct_dependents", "contracts"):
            add("files", _strings(impact, key), "impact.yaml", policy != "LOCAL")
        for group, records in (
            ("requirements", source.requirements),
            ("invariants", source.invariants),
        ):
            for record in records:
                for case in record.get("test_plan", {}).get("cases", []):
                    add("tests", case.get("tests", []), f"{group}.yaml", False)
        for record in source.findings:
            declaration = f"findings/{record['id']}.yaml"
            path = record.get("regression_test", {}).get("path")
            if path:
                add(
                    "tests",
                    [path],
                    declaration,
                    record["status"] in OPEN_FINDING_STATUSES,
                )
            location = record.get("location", {}).get("file")
            if location:
                add("files", [location], declaration, False)
        for record in source.decisions:
            if record.get("task_id") != task_id:
                continue
            add(
                "files",
                record.get("scope", []),
                f"decisions/{record['id']}.yaml",
                record["status"] == "ACCEPTED" and policy == "EXPANDED",
            )
        if source.observability is not None:
            add(
                "files",
                source.observability["applicability"].get("inspected_paths", []),
                "observability.yaml",
                False,
            )
        for group, entries in candidates.items():
            for path, (name, allowed) in sorted(entries.items()):
                broad = policy == "LOCAL" and _broad(path)
                if full or (allowed and not broad):
                    working[group].append(path)
                else:
                    reason = (
                        "broad_context_requires_expansion"
                        if broad
                        else "outside_context_policy"
                    )
                    omit(
                        f"{'file' if group == 'files' else 'test'}:{path}", name, reason
                    )
        return ContextSelection(deepcopy(working), deepcopy(omitted))

"""Exact verification batches. Invalid native proof cannot be reused as success."""

from dataclasses import dataclass

from .execution_proof import valid

_RESOURCES = frozenset({"database", "port", "workspace"})


class BatchPlanError(ValueError):
    pass


@dataclass(frozen=True)
class Batch:
    batch_id: str
    selector: str
    report_path: str
    required_tests: tuple
    resources: frozenset


@dataclass(frozen=True)
class BatchPlan:
    batches: tuple
    serial_groups: tuple
    required_tests: tuple
    historical_obligations: tuple = ()


def _relative(path):
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return False
    return all(part not in {"", ".", ".."} for part in path.split("/"))


def plan_batches(batches, *, historical_obligations=()):
    if not batches:
        raise BatchPlanError("VERIFICATION_BATCH_REQUIRED")
    seen = set()
    normalized = []
    for batch in batches:
        if (not isinstance(batch.batch_id, str) or not batch.batch_id
                or batch.batch_id in seen or not batch.selector or not _relative(batch.report_path)):
            raise BatchPlanError("VERIFICATION_BATCH_INVALID")
        if not batch.required_tests or any(not _relative(test.split("::", 1)[0]) or not test for test in batch.required_tests):
            raise BatchPlanError("VERIFICATION_BATCH_INVALID")
        if any(resource not in _RESOURCES for resource in batch.resources):
            raise BatchPlanError("VERIFICATION_RESOURCE_INVALID")
        seen.add(batch.batch_id)
        normalized.append(batch)
    parent = {batch.batch_id: batch.batch_id for batch in normalized}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    by_resource = {}
    for batch in normalized:
        for resource in batch.resources:
            by_resource.setdefault(resource, []).append(batch.batch_id)
    for identifiers in by_resource.values():
        for other in identifiers[1:]:
            parent[find(other)] = find(identifiers[0])
    groups = {}
    for batch in normalized:
        groups.setdefault(find(batch.batch_id), []).append(batch.batch_id)
    required = tuple(dict.fromkeys(test for batch in normalized for test in batch.required_tests))
    serial = tuple(tuple(identifiers) for identifiers in groups.values() if len(identifiers) > 1)
    return BatchPlan(tuple(normalized), serial, required, tuple(historical_obligations))


def _touches(path, changed):
    return any(path == item or path.startswith(item.rstrip("/") + "/") for item in changed)


def rerun(plan, *, failed=(), changed=(), owners=None, receipts=None):
    """Failed and affected batches only. A receipt skips work only when it is native success."""
    owners = owners or {}
    receipts = receipts or {}
    affected = {
        test for test, paths in owners.items()
        if any(_touches(path, changed) for path in paths)
    }
    selected = set(failed)
    for batch in plan.batches:
        if any(test in affected for test in batch.required_tests):
            selected.add(batch.batch_id)
        receipt = receipts.get(batch.batch_id)
        if receipt is not None and not valid(receipt, True):
            selected.add(batch.batch_id)
    return tuple(batch.batch_id for batch in plan.batches if batch.batch_id in selected)


def append_observation(history, record):
    """Keep earlier RED observations. A later receipt does not replace them."""
    return (*history, record)


def progress(plan, *, passed_batches, historical_open=()):
    return {
        "increment_complete": set(passed_batches) >= {batch.batch_id for batch in plan.batches},
        "historical_obligations": list(historical_open or plan.historical_obligations),
        "partial_done": False,
    }

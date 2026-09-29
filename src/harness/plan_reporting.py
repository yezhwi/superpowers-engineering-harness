"""Pure body-free projections for Plan status and Gate preview surfaces."""

from __future__ import annotations

from copy import deepcopy

_INVALID_PROOF_CODES = frozenset(
    {"PLAN_DISPOSITION_INVALID", "PLAN_PROTECTED_PATHS_MODIFIED"}
)


def _proof_branch(item: dict) -> str:
    has_tests = bool(item.get("test_case_refs", []))
    has_surfaces = bool(item.get("surfaces", []))
    if has_tests and has_surfaces:
        return "tests_and_surfaces"
    if has_tests:
        return "tests"
    if has_surfaces:
        return "surfaces"
    return "none"


def plan_item_reports(plan: dict | None, assessment) -> tuple[dict, ...]:
    """Project canonical items and assessment facts without proof bodies."""
    if plan is None:
        return ()
    trusted = assessment.projection is not None
    projection = assessment.projection or {}
    blockers_by_item: dict[str, list] = {}
    for blocker in assessment.blockers:
        if blocker.source is not None:
            blockers_by_item.setdefault(blocker.source, []).append(blocker)

    rows = []
    for item in plan["items"]:
        item_id = item["id"]
        branch = _proof_branch(item)
        status = projection.get(item_id, {}).get("status", "PENDING") if trusted else None
        item_blockers = blockers_by_item.get(item_id, [])
        codes = {blocker.code for blocker in item_blockers}
        if not trusted:
            health = "untrusted"
        elif status in {"PENDING", "IN_PROGRESS", "BLOCKED", "SKIPPED", "SUPERSEDED"} or branch == "none":
            health = "not_applicable"
        elif "PLAN_PROOF_MISSING" in codes:
            health = "missing"
        elif codes & _INVALID_PROOF_CODES:
            health = "invalid"
        else:
            health = "valid"
        rows.append(
            {
                "id": item_id,
                "status": status,
                "proof_branch": branch,
                "proof_health": health,
                "blockers": [
                    {"code": blocker.code, "recovery": blocker.recover_to}
                    for blocker in item_blockers
                ],
            }
        )
    return tuple(rows)


def with_verbose_items(report: dict, plan: dict | None, assessment) -> dict:
    """Return report copy with closed item rows appended last."""
    result = deepcopy(report)
    result["items"] = list(plan_item_reports(plan, assessment))
    return result


def gate_plan_preview(
    task: dict,
    plan: dict | None,
    assessment,
) -> tuple[str, ...]:
    """Render compact body-free Plan facts from one carried assessment."""
    mode = (task.get("plan_reconciliation") or {}).get("mode") or "final"
    lines = ["Plan:", f"  Mode: {mode}"]
    if plan is None or assessment.projection is None:
        lines.extend(["  Progress: unavailable", "  Next: -"])
    else:
        statuses = {
            item["id"]: assessment.projection.get(item["id"], {}).get(
                "status", "PENDING"
            )
            for item in plan["items"]
        }
        terminal = {"COMPLETE", "SKIPPED", "SUPERSEDED"}
        reconciled = sum(status in terminal for status in statuses.values())
        next_item = next(
            (item["id"] for item in plan["items"] if statuses[item["id"]] not in terminal),
            None,
        )
        lines.extend(
            [
                f"  Progress: {reconciled} / {len(plan['items'])} reconciled",
                f"  Next: {next_item or '-'}",
            ]
        )
    lines.append(
        f"  Final: {'BLOCKED' if assessment.final_blockers else 'PASS'}"
    )
    plan_blockers = [
        blocker for blocker in assessment.blockers if blocker.code.startswith("PLAN_")
    ]
    if plan_blockers:
        lines.append("  Blockers:")
        for blocker in plan_blockers:
            lines.append(f"- {blocker.code}: {blocker.message}")
            if blocker.source:
                lines.append(f"  source: {blocker.source}")
    return tuple(lines)

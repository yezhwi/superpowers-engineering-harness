"""Soft budgets for Harness-observable FAST evidence actions."""

import hashlib

LIMITS = {"test": 2, "build": 1, "retry": 1}


class BudgetOverrideRequired(ValueError):
    pass


def _command_hash(command: str) -> str:
    return "sha256:" + hashlib.sha256(command.encode()).hexdigest()


def is_retry(task: dict, command: str) -> bool:
    return (task.get("budget") or {}).get("last_failed_command") == _command_hash(
        command
    )


def record_failure(task: dict, command: str) -> None:
    task.setdefault("budget", {})["last_failed_command"] = _command_hash(command)


def budget_action(evidence_type: str, exit_code: int, command: str) -> str | None:
    if evidence_type == "unit_test":
        return "test"
    if evidence_type == "build":
        return "build"
    return None


def check_budget(task: dict, action: str, override: dict | None) -> None:
    if (task.get("risk") or {}).get("profile") != "FAST":
        return
    budget = task.get("budget") or {}
    if budget.get(f"{action}_runs", 0) < LIMITS[action]:
        return
    if not isinstance(override, dict) or not all(
        override.get(key) for key in ("reason", "evidence", "hypothesis")
    ):
        raise BudgetOverrideRequired("BUDGET_OVERRIDE_REQUIRED")


def record_budget(task: dict, action: str, override: dict | None) -> None:
    budget = task.setdefault(
        "budget", {"test_runs": 0, "build_runs": 0, "retry_runs": 0, "overrides": []}
    )
    budget[f"{action}_runs"] += 1
    if override:
        budget["overrides"].append({"action": action, **override})

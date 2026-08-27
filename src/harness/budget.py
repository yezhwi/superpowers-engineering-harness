"""Soft budgets for Harness-observable FAST evidence actions."""

LIMITS = {"test": 2, "build": 1, "retry": 1}


class BudgetOverrideRequired(ValueError):
    pass


def check_budget(task: dict, action: str, override: dict | None) -> None:
    if (task.get("risk") or {}).get("profile") != "FAST":
        return
    budget = task.get("budget") or {}
    if budget.get(f"{action}_runs", 0) < LIMITS[action]:
        return
    if not isinstance(override, dict) or not all(override.get(key) for key in ("reason", "evidence", "hypothesis")):
        raise BudgetOverrideRequired("BUDGET_OVERRIDE_REQUIRED")


def record_budget(task: dict, action: str, override: dict | None) -> None:
    budget = task.setdefault("budget", {"test_runs": 0, "build_runs": 0, "retry_runs": 0, "overrides": []})
    budget[f"{action}_runs"] += 1
    if override:
        budget["overrides"].append({"action": action, **override})

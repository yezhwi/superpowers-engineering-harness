"""Local deterministic Harness telemetry."""

import datetime
import json
from pathlib import Path
from typing import Protocol, TypedDict

import yaml

from .telemetry_lock import telemetry_lock
from .transaction import atomic_write


class AgentUsage(TypedDict):
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    tool_calls: int | None
    search_rounds: int | None
    file_reads: int | None
    source: str | None


class UsageProvider(Protocol):
    def get_usage(self) -> AgentUsage: ...


class TelemetryError(ValueError):
    """Invalid usage input or task identity."""


_COUNTERS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tool_calls",
    "search_rounds",
    "file_reads",
)
_USAGE_FIELDS = ("provider", "model", *_COUNTERS, "source")


def normalize_usage(usage: dict) -> AgentUsage:
    """Validate usage shape for telemetry reports and benchmark artifacts."""
    if not isinstance(usage, dict) or set(usage) - set(_USAGE_FIELDS):
        raise TelemetryError("TELEMETRY_USAGE_INVALID")
    usage = {key: usage.get(key) for key in _USAGE_FIELDS}
    for key in _COUNTERS:
        value = usage[key]
        if value is not None and (type(value) is not int or value < 0):
            raise TelemetryError("TELEMETRY_USAGE_INVALID")
    if any(
        usage[key] is not None and not isinstance(usage[key], str)
        for key in ("provider", "model")
    ):
        raise TelemetryError("TELEMETRY_USAGE_INVALID")
    if usage["source"] not in (None, "runtime", "provider", "estimated"):
        raise TelemetryError("TELEMETRY_USAGE_INVALID")
    tokens = [usage[key] for key in _COUNTERS[:3]]
    if any(value is not None for value in tokens) and usage["source"] is None:
        raise TelemetryError("TELEMETRY_USAGE_INVALID")
    if (
        all(value is not None for value in tokens)
        and tokens[0] + tokens[1] != tokens[2]
    ):
        raise TelemetryError("TELEMETRY_USAGE_INVALID")
    return usage


def _normalize_usage(report: dict) -> AgentUsage:
    if (
        not isinstance(report, dict)
        or set(report) != {"task_id", "usage"}
        or not isinstance(report["task_id"], str)
        or not report["task_id"]
    ):
        raise TelemetryError("TELEMETRY_USAGE_INVALID")
    return normalize_usage(report["usage"])


def _previous(harness_dir: Path, task: dict) -> dict:
    try:
        data = json.loads((harness_dir / "telemetry.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("task_id") != (
        task.get("task") or {}
    ).get("id"):
        return {}
    return data


def report_usage(harness_dir: Path, report: dict) -> dict:
    """Replace host measurements with one task-bound cumulative snapshot."""
    usage = _normalize_usage(report)
    with telemetry_lock(harness_dir):
        task = _current_task(harness_dir)
        if task["task"]["id"] is None:
            raise TelemetryError("INVALID_HARNESS_STATE")
        if task["task"]["id"] != report["task_id"]:
            raise TelemetryError("TELEMETRY_TASK_MISMATCH")
        data = _previous(harness_dir, task) or _local_facts(
            task, {}, None, count_call=False
        )
        data["usage"] = usage
        data["agent"] = {
            "tool_calls": usage["tool_calls"],
            "search_rounds": usage["search_rounds"],
            "file_reads": usage["file_reads"],
            "token_estimate": None,
        }
        atomic_write(
            harness_dir / "telemetry.json", json.dumps(data, indent=2).encode()
        )
        return data


def report_provider_usage(
    harness_dir: Path, task_id: str, provider: UsageProvider
) -> dict:
    """Persist injected host usage through normal task-bound validation."""
    return report_usage(
        harness_dir, {"task_id": task_id, "usage": provider.get_usage()}
    )


def _current_task(harness_dir: Path) -> dict:
    try:
        task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
        task_id = task["task"]["id"]
        # Legacy templates allow null IDs for local telemetry, never host ingest.
        if task_id is not None and (not isinstance(task_id, str) or not task_id):
            raise ValueError("task id invalid")
        return task
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise TelemetryError("INVALID_HARNESS_STATE") from exc


def preserve_usage_for_replacement(harness_dir: Path, staged: Path) -> None:
    """Carry the latest host snapshot into same-task replacements under lock."""
    if not (harness_dir / "telemetry.json").is_file():
        return
    task = _current_task(staged)
    if task["task"]["id"] != _current_task(harness_dir)["task"]["id"]:
        return
    current = _previous(harness_dir, task)
    data = _previous(staged, task) or _local_facts(task, {}, None, count_call=False)
    data["usage"] = current.get("usage")
    if "agent" in current:
        data["agent"] = current["agent"]
    atomic_write(staged / "telemetry.json", json.dumps(data, indent=2).encode())


def _elapsed_seconds(created_at: str | None, now: str) -> int | None:
    if not created_at:
        return None
    try:
        return max(
            0,
            int(
                (
                    datetime.datetime.fromisoformat(now)
                    - datetime.datetime.fromisoformat(created_at)
                ).total_seconds()
            ),
        )
    except ValueError:
        return None


def update_telemetry(harness_dir: Path, task: dict, *, now: str | None = None) -> dict:
    with telemetry_lock(harness_dir):
        if (harness_dir / "current-task.yaml").exists():
            current = _current_task(harness_dir)
            if current["task"]["id"] != (task.get("task") or {}).get("id"):
                raise TelemetryError("TELEMETRY_TASK_MISMATCH")
        data = _local_facts(task, _previous(harness_dir, task), now)
        atomic_write(
            harness_dir / "telemetry.json", json.dumps(data, indent=2).encode()
        )
        return data


def _local_facts(
    task: dict, previous: dict, now: str | None, *, count_call: bool = True
) -> dict:
    now = now or datetime.datetime.now(datetime.UTC).isoformat()
    risk = task.get("risk") or {}
    budget = task.get("budget") or {}
    data = {
        "task_id": (task.get("task") or {}).get("id"),
        "risk_level": risk.get("level"),
        "workflow_profile": risk.get("profile"),
        "evidence": {
            key: budget.get(key, 0) for key in ("test_runs", "build_runs", "retry_runs")
        },
        "elapsed_seconds": _elapsed_seconds(
            (task.get("timestamps") or {}).get("created_at"), now
        ),
        "harness_command_calls": int(previous.get("harness_command_calls", 0))
        + int(count_call),
        "gate_result": (task.get("gate") or {}).get("status"),
        "rework_count": task.get("iteration"),
        "risk_escalations": len(risk.get("escalation_history") or []),
        "agent": previous.get(
            "agent", {"tool_calls": None, "search_rounds": None, "token_estimate": None}
        ),
        "usage": previous.get("usage"),
        "token_estimate": None,
    }
    return data

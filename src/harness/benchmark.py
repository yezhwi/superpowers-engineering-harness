"""Deterministic local benchmark fixture reporting."""

import json
import math
from pathlib import Path

import yaml

from harness.telemetry import TelemetryError, normalize_usage

INCONCLUSIVE = "INCONCLUSIVE"


def benchmark(*, tasks: list[dict], alignments: list[dict], findings: list[dict]) -> dict:
    """Aggregate alignment control-plane metrics from supplied persisted records."""
    completed = {task["id"] for task in tasks if task.get("state") == "DONE"}
    alignment_by_task = {item.get("task_id"): item for item in alignments}
    drift = {
        finding.get("task_id") for finding in findings
        if finding.get("task_id") in completed
        and finding.get("category") == "alignment"
    }
    questions = {
        task_id for task_id in completed
        if alignment_by_task.get(task_id, {}).get("open_questions")
    }
    rework = {
        task["id"] for task in tasks if task.get("id") in completed
        and any(
            previous in {"VERIFYING", "REVIEWING"} and current == "IMPLEMENTING"
            for previous, current in zip(task.get("history", []), task.get("history", [])[1:])
        )
    }
    denominator = len(completed)
    rate = lambda count: count / denominator if denominator else None
    return {
        "completed_tasks": denominator,
        "drift": {"count": len(drift), "rate": rate(len(drift))},
        "questions": {"count": len(questions), "rate": rate(len(questions))},
        "rework": {"count": len(rework), "rate": rate(len(rework))},
    }
_COUNTER_METRICS = {"token_estimate", "tool_calls", "search_rounds", "file_reads"}
_AGENT_FIELDS = _COUNTER_METRICS


def _valid_metrics(metrics: dict) -> bool:
    for key, value in metrics.items():
        if (
            key in _COUNTER_METRICS
            and value is not None
            and (type(value) is not int or value < 0)
        ):
            return False
        if (
            key == "elapsed_seconds"
            and value is not None
            and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or (isinstance(value, float) and not math.isfinite(value))
                or value < 0
            )
        ):
            return False
    return True


def _run_metrics(run: dict) -> dict:
    metrics = dict(run.get("metrics", {}))
    agent = run.get("agent", {})
    return {
        **agent,
        **{key: value for key, value in metrics.items() if value is not None},
    }


def tokens_per_success(attempts: list[dict]) -> float | int | str:
    """Return all attempted token cost divided by known successful attempts."""
    if not attempts:
        return INCONCLUSIVE
    total = 0
    successes = 0
    for attempt in attempts:
        tokens = attempt.get("total_tokens")
        success = attempt.get("success")
        if (
            not isinstance(tokens, (int, float))
            or isinstance(tokens, bool)
            or success not in {True, False}
        ):
            return INCONCLUSIVE
        total += tokens
        successes += success
    return total / successes if successes else INCONCLUSIVE


def _metric_per_success(runs: list[dict], key: str) -> float | int | str:
    values = [run.get(key) for run in runs]
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in values
    ):
        return INCONCLUSIVE
    successes = sum(run["success"] for run in runs)
    return sum(values) / successes if successes else INCONCLUSIVE


def summarize_runs(runs: list[dict]) -> dict | str:
    """Summarize three or more complete attempts without inventing metrics."""
    if len(runs) < 3:
        return INCONCLUSIVE
    tps = tokens_per_success(runs)
    if tps == INCONCLUSIVE:
        return INCONCLUSIVE
    tokens = [run["total_tokens"] for run in runs]
    if not all(isinstance(token, (int, float)) for token in tokens):
        return INCONCLUSIVE
    ordered = sorted(tokens)
    return {
        "median_tokens": _median(ordered),
        "p90_tokens": float(ordered[-(-9 * len(ordered) // 10) - 1]),
        "success_rate": sum(run["success"] for run in runs) / len(runs),
        "tokens_per_success": tps,
        "tool_calls_per_success": _metric_per_success(runs, "tool_calls"),
        "elapsed_per_success": _metric_per_success(runs, "elapsed_seconds"),
        "search_rounds_per_success": _metric_per_success(runs, "search_rounds"),
        "file_reads_per_success": _metric_per_success(runs, "file_reads"),
    }


def validate_corpus(corpus: Path) -> list[dict]:
    profiles = {"Q0": None, "Q1": "FAST", "Q2": "STANDARD", "Q3": "STRICT"}
    expected = {"Q0": 10, "Q1": 20, "Q2": 10, "Q3": 10}
    rows = []
    try:
        for directory in sorted(corpus.iterdir()):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.yaml")):
                data = yaml.safe_load(path.read_text())
                required = {
                    "id",
                    "level",
                    "expected_profile",
                    "scenario",
                    "risk_tags",
                    "required_correctness",
                }
                if (
                    not isinstance(data, dict)
                    or required - set(data)
                    or directory.name != data["level"].lower()
                ):
                    raise ValueError
                if (
                    data["level"] not in profiles
                    or data["expected_profile"] != profiles[data["level"]]
                ):
                    raise ValueError
                if (
                    not isinstance(data["id"], str)
                    or not data["id"].startswith(data["level"].lower() + "-")
                    or not isinstance(data["scenario"], str)
                    or not data["scenario"]
                ):
                    raise ValueError
                if not isinstance(data["risk_tags"], list) or not all(
                    isinstance(tag, str) and tag for tag in data["risk_tags"]
                ):
                    raise ValueError
                if not isinstance(data["required_correctness"], list) or (
                    data["level"] == "Q0" and data["required_correctness"]
                ):
                    raise ValueError
                rows.append(data)
        if (
            len({row["id"] for row in rows}) != len(rows)
            or {level: sum(row["level"] == level for row in rows) for level in expected}
            != expected
        ):
            raise ValueError
        return rows
    except (OSError, TypeError, yaml.YAMLError, ValueError) as exc:
        raise ValueError("BENCHMARK_CORPUS_INVALID") from exc


def _artifact_data(path: Path, fixture_id: str, mode: str) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(data, dict)
        or data.get("fixture_id") != fixture_id
        or data.get("mode") != mode
    ):
        return None
    return data


def _artifact(data: dict | None):
    if data is None:
        return None
    runs = data.get("runs", [data])
    if not isinstance(runs, list) or not runs:
        return None
    for run in runs:
        if (
            not isinstance(run, dict)
            or not isinstance(run.get("correctness"), dict)
            or not isinstance(run.get("metrics"), dict)
        ):
            return None
        if not _valid_metrics(run["metrics"]):
            return None
        if "agent" in run and (
            not isinstance(run["agent"], dict)
            or set(run["agent"]) - _AGENT_FIELDS
            or not _valid_metrics(run["agent"])
        ):
            return None
        if any(
            value is not None
            and run["metrics"].get(key) is not None
            and value != run["metrics"][key]
            for key, value in run.get("agent", {}).items()
        ):
            return None
        if "usage" in run:
            try:
                run["usage"] = normalize_usage(run["usage"])
            except TelemetryError:
                return None
    return data


def _known_failure(data: dict | None, required: list[str]) -> bool:
    """Keep explicit safety/correctness failures above invalid efficiency data."""
    if data is None:
        return False
    if data.get("integrity") is False:
        return True
    correctness = data.get("correctness")
    if isinstance(correctness, dict) and (
        any(correctness.get(key) is False for key in required)
        or correctness.get("integrity") is False
    ):
        return True
    runs = data.get("runs", [data])
    if not isinstance(runs, list) or not runs:
        return False
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("integrity") is False:
            return True
        if not isinstance(run.get("correctness"), dict):
            continue
        if (
            any(run["correctness"].get(key) is False for key in required)
            or run["correctness"].get("integrity") is False
            or run.get("integrity") is False
        ):
            return True
    return False


def _median(values: list[int | float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        float(ordered[middle])
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )


def _experiment_verdict(rows: list[dict]) -> dict:
    """Apply v0.2.8 safety/correctness precedence before efficiency claims."""
    artifacts = [
        artifact
        for row in rows
        for artifact in (row.get("baseline"), row.get("adaptive"))
        if artifact is not None
    ]
    if any(
        row["status"] == "CORRECTNESS_REGRESSION" or row.get("known_failure")
        for row in rows
    ) or any(
        artifact.get("correctness", {}).get("integrity") is False
        or artifact.get("integrity") is False
        or any(
            run.get("correctness", {}).get("integrity") is False
            or run.get("integrity") is False
            for run in _runs(artifact)
        )
        for artifact in artifacts
    ):
        return {"status": "FAIL", "confidence": "high"}
    if any(row["status"] == INCONCLUSIVE for row in rows):
        return {"status": INCONCLUSIVE, "confidence": "high"}
    usage = [run.get("usage") for artifact in artifacts for run in _runs(artifact)]
    if any(
        isinstance(item, dict) and item.get("source") == "estimated" for item in usage
    ):
        return {"status": INCONCLUSIVE, "confidence": "low"}
    q1 = [row for row in rows if row.get("level") == "Q1"]
    if len(q1) != 20 or any(
        len(_runs(row.get(mode))) < 3 for row in q1 for mode in ("baseline", "adaptive")
    ):
        return {"status": INCONCLUSIVE, "confidence": "high"}
    token_pairs = [
        (run.get("usage", {}).get("total_tokens"), mode)
        for row in q1
        for mode in ("baseline", "adaptive")
        for run in _runs(row[mode])
    ]
    baseline_tokens = [value for value, mode in token_pairs if mode == "baseline"]
    adaptive_tokens = [value for value, mode in token_pairs if mode == "adaptive"]
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in baseline_tokens + adaptive_tokens
    ):
        return {"status": INCONCLUSIVE, "confidence": "high"}
    tokens_per_success_by_mode = {
        mode: tokens_per_success(
            [
                attempt
                for row in q1
                for attempt in _usage_attempts(row, mode)
            ]
        )
        for mode in ("baseline", "adaptive")
    }
    if INCONCLUSIVE in tokens_per_success_by_mode.values():
        return {"status": INCONCLUSIVE, "confidence": "high"}
    improvement = False
    for metric in ("tool_calls", "search_rounds", "file_reads", "elapsed_seconds"):
        pairs = [
            (_run_metrics(run).get(metric), mode)
            for row in q1
            for mode in ("baseline", "adaptive")
            for run in _runs(row[mode])
        ]
        baseline_values = [value for value, mode in pairs if mode == "baseline"]
        adaptive_values = [value for value, mode in pairs if mode == "adaptive"]
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in baseline_values + adaptive_values
        ):
            return {"status": INCONCLUSIVE, "confidence": "high"}
        improvement = improvement or _median(adaptive_values) < _median(baseline_values)
    if (
        _median(adaptive_tokens) < _median(baseline_tokens)
        and tokens_per_success_by_mode["adaptive"]
        < tokens_per_success_by_mode["baseline"]
        and improvement
    ):
        return {"status": "PASS", "confidence": "high"}
    return {"status": "FAIL", "confidence": "high"}


def _runs(artifact: dict | None) -> list[dict]:
    if artifact is None:
        return []
    return artifact.get("runs", [artifact])


def _correctness(artifact: dict | None, required: list[str]) -> bool | None:
    runs = _runs(artifact)
    if not runs:
        return None
    values = [run["correctness"].get(key) for run in runs for key in required]
    if any(value not in {True, False} for value in values):
        return None
    return all(values)


def _metrics(artifact: dict | None) -> dict:
    return (artifact or {}).get("metrics", {})


def _run_attempt(run: dict, required: list[str]) -> dict:
    return {
        "total_tokens": run.get("usage", {}).get("total_tokens"),
        "success": _correctness({"runs": [run]}, required),
    }


def _usage_attempts(row: dict, mode: str) -> list[dict]:
    runs = _runs(row.get(mode))
    return (
        [_run_attempt(run, row["required_correctness"]) for run in runs]
        if runs
        else [{"total_tokens": None, "success": None}]
    )


def compare_benchmarks(fixtures: Path, baseline: Path, adaptive: Path) -> dict:
    rows = []
    for path in sorted(fixtures.glob("*.yaml")):
        fixture = yaml.safe_load(path.read_text())
        if (
            not isinstance(fixture, dict)
            or not isinstance(fixture.get("id"), str)
            or not isinstance(fixture.get("required_correctness"), list)
        ):
            raise ValueError(f"BENCHMARK_FIXTURE_INVALID: {path}")
        fid = fixture["id"]
        before_data = _artifact_data(baseline / f"{fid}.json", fid, "baseline")
        after_data = _artifact_data(adaptive / f"{fid}.json", fid, "adaptive")
        before = _artifact(before_data)
        after = _artifact(after_data)
        status = "CORRECTNESS_PRESERVED"
        if (
            before is None
            or after is None
            or _correctness(before, fixture["required_correctness"]) is None
            or _correctness(after, fixture["required_correctness"]) is None
        ):
            status = "INCONCLUSIVE"
        elif _correctness(after, fixture["required_correctness"]) is not True:
            status = "CORRECTNESS_REGRESSION"
        metrics = {}
        for key in ("token_estimate", "tool_calls", "elapsed_seconds"):
            left = _metrics(before).get(key)
            right = _metrics(after).get(key)
            metrics[f"{key}_delta"] = (
                right - left
                if isinstance(left, (int, float)) and isinstance(right, (int, float))
                else None
            )
        row = {
            "id": fid,
            "level": fixture.get("level"),
            "required_correctness": fixture["required_correctness"],
            "status": status,
            "known_failure": _known_failure(
                before_data, fixture["required_correctness"]
            )
            or _known_failure(after_data, fixture["required_correctness"]),
            "metrics": metrics,
            "baseline": before,
            "adaptive": after,
        }
        row["tokens_per_success"] = {
            mode: tokens_per_success(_usage_attempts(row, mode))
            for mode in ("baseline", "adaptive")
        }
        row["run_statistics"] = {
            mode: summarize_runs(
                [
                    {
                        **_run_attempt(run, fixture["required_correctness"]),
                        "tool_calls": _run_metrics(run).get("tool_calls"),
                        "search_rounds": _run_metrics(run).get("search_rounds"),
                        "file_reads": _run_metrics(run).get("file_reads"),
                        "elapsed_seconds": _run_metrics(run).get("elapsed_seconds"),
                    }
                    for run in _runs(artifact)
                ]
            )
            for mode, artifact in (("baseline", before), ("adaptive", after))
        }
        rows.append(row)
    statuses = {row["status"] for row in rows}
    overall = (
        "CORRECTNESS_REGRESSION"
        if "CORRECTNESS_REGRESSION" in statuses
        else ("INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "CORRECTNESS_PRESERVED")
    )
    return {
        "overall": overall,
        "fixtures": rows,
        "metrics": {
            "tokens_per_success": {
                mode: tokens_per_success(
                    [attempt for row in rows for attempt in _usage_attempts(row, mode)]
                )
                for mode in ("baseline", "adaptive")
            }
        },
        "experiment": _experiment_verdict(rows),
    }


def evaluate_acceptance(report: dict, fixtures: list[dict]) -> dict:
    rows = report.get("fixtures", [])
    result = {}
    q1 = [row for row in rows if row.get("level") == "Q1"]
    for ac, metric in (
        ("AC16", "tool_calls"),
        ("AC17", "token_estimate"),
        ("AC18", "elapsed_seconds"),
    ):
        if len(q1) != 20:
            result[ac] = {"status": "INCONCLUSIVE"}
            continue
        pairs = [
            (
                (row.get("baseline") or {}).get("metrics", {}).get(metric),
                (row.get("adaptive") or {}).get("metrics", {}).get(metric),
            )
            for row in q1
        ]
        if not all(
            isinstance(left, (int, float)) and isinstance(right, (int, float))
            for left, right in pairs
        ):
            result[ac] = {"status": "INCONCLUSIVE"}
        else:
            result[ac] = {
                "status": "PASS"
                if sum(right for _, right in pairs) / 20
                < sum(left for left, _ in pairs) / 20
                else "FAIL"
            }
    expected_rows = len(fixtures) if fixtures else len(rows)
    complete = (
        expected_rows == 50
        and len(rows) == expected_rows
        and all(
            row.get("status") == "CORRECTNESS_PRESERVED"
            and all(
                (row.get("baseline") or {}).get("correctness", {}).get(key) is True
                and (row.get("adaptive") or {}).get("correctness", {}).get(key) is True
                for key in next(
                    (
                        item.get("required_correctness", [])
                        for item in fixtures
                        if item.get("id") == row.get("id")
                    ),
                    [],
                )
            )
            for row in rows
        )
    )
    result["AC19"] = {"status": "PASS" if complete else "INCONCLUSIVE"}
    q23 = [row for row in rows if row.get("level") in {"Q2", "Q3"}]
    result["AC20"] = {
        "status": "PASS" if complete and len(q23) == 20 else "INCONCLUSIVE"
    }
    return result


def run_benchmarks(fixtures: Path, telemetry: Path) -> dict:
    data = json.loads(telemetry.read_text())
    rows = []
    for path in sorted(fixtures.glob("*.yaml")):
        fixture = yaml.safe_load(path.read_text())
        required = {"id", "risk_level", "expected_profile", "expected_gate"}
        if not isinstance(fixture, dict) or required - set(fixture):
            raise ValueError(f"BENCHMARK_FIXTURE_INVALID: {path}")
        if (
            data.get("workflow_profile") != fixture["expected_profile"]
            or data.get("gate_result") != fixture["expected_gate"]
        ):
            raise ValueError(f"BENCHMARK_EXPECTATION_MISMATCH: {fixture['id']}")
        rows.append(fixture)
    return {"fixtures": rows, "metrics": {"token_estimate": data.get("token_estimate")}}

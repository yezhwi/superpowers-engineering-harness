"""Deterministic local benchmark fixture reporting."""

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import yaml

from harness.architecture import (
    ArchitectureError,
    architecture_fingerprint,
    load_architecture_document,
)
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


_ARCHITECTURE_FIXTURE_KEYS = {
    "version", "id", "experiment", "scenario", "treatment", "inputs", "expected"
}
_ARCHITECTURE_TASK_KEYS = {"declared_modules", "protected_paths", "adopted_paths"}
_GIT_KINDS = {"added", "modified", "deleted", "untracked"}
_MODULE_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_DIAGNOSTIC_CODES = {
    "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
    "ARCHITECTURE_OWNERSHIP_AMBIGUOUS",
}
_LEAP_SECOND_DATES = {
    "1972-06-30", "1972-12-31", "1973-12-31", "1974-12-31",
    "1975-12-31", "1976-12-31", "1977-12-31", "1978-12-31",
    "1979-12-31", "1981-06-30", "1982-06-30", "1983-06-30",
    "1985-06-30", "1987-12-31", "1989-12-31", "1990-12-31",
    "1992-06-30", "1993-06-30", "1994-06-30", "1995-12-31",
    "1997-06-30", "1998-12-31", "2005-12-31", "2008-12-31",
    "2012-06-30", "2015-06-30", "2016-12-31",
}
_IDENTITY_CODES = _DIAGNOSTIC_CODES | {
    "ARCHITECTURE_REQUIRED",
    "ARCHITECTURE_SCOPE_INVALID",
    "ARCHITECTURE_EVIDENCE_INVALID",
    "ARCHITECTURE_SCOPE_DRIFT",
    "ARCHITECTURE_OWNERSHIP_EMPTY",
}


def _exact_keys(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _valid_text(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _fixture_path(value: object, *, allow_patterns: bool = False) -> bool:
    if (
        not _valid_text(value)
        or "\\" in value
        or value in {".", ".."}
        or value.startswith("/")
        or str(PurePosixPath(value)) != value
        or (not allow_patterns and any(char in value for char in "*?[]{}"))
    ):
        return False
    return all(part not in {"", ".", ".."} for part in PurePosixPath(value).parts)


def _string_list(value: object, *, paths: bool = False) -> bool:
    if not isinstance(value, list) or not all(_valid_text(item) for item in value):
        return False
    return len(value) == len(set(value)) and (
        not paths
        or all(_fixture_path(item, allow_patterns=True) for item in value)
    )


def _valid_module_id(value: object) -> bool:
    return (
        _valid_text(value)
        and len(value) <= 64
        and _MODULE_ID.fullmatch(value) is not None
    )


def _module_id_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(_valid_module_id(item) for item in value)
        and len(value) == len(set(value))
    )


def _validate_architecture_fixture(data: object, directory: str) -> dict:
    if not _exact_keys(data, _ARCHITECTURE_FIXTURE_KEYS):
        raise ValueError
    assert isinstance(data, dict)
    experiment = data["experiment"]
    if (
        type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["id"], str)
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", data["id"]) is None
        or not isinstance(data["scenario"], str)
        or not data["scenario"]
        or (directory, experiment) not in {
            ("drift", "drift_detection"),
            ("context", "context_recovery"),
        }
    ):
        raise ValueError

    inputs = data["inputs"]
    input_keys = {"task", "architecture", "git", "token_budget"}
    if experiment == "context_recovery":
        input_keys.update({"architecture_mode", "architecture_assessment"})
    if not _exact_keys(inputs, input_keys):
        raise ValueError
    if type(inputs["token_budget"]) is not int or inputs["token_budget"] <= 0:
        raise ValueError
    task = inputs["task"]
    if (
        not _exact_keys(task, _ARCHITECTURE_TASK_KEYS)
        or not _module_id_list(task["declared_modules"])
        or not all(
            _string_list(task[key], paths=True)
            for key in ("protected_paths", "adopted_paths")
        )
    ):
        raise ValueError
    model = load_architecture_document(inputs["architecture"])
    model_ids = {module.id for module in model.modules}
    if not set(task["declared_modules"]) <= model_ids:
        raise ValueError
    if experiment == "context_recovery":
        assessment = inputs["architecture_assessment"]
        declared = sorted(task["declared_modules"])
        by_id = {module.id: module for module in model.modules}
        relevant = set(declared)
        for module_id in declared:
            relevant.update(by_id[module_id].depends_on)
        relevant_records = [
            {
                "id": by_id[module_id].id,
                "name": by_id[module_id].name,
                "responsibility": by_id[module_id].responsibility,
                "depends_on": sorted(by_id[module_id].depends_on),
            }
            for module_id in sorted(relevant)
        ]
        if inputs["architecture_mode"] != "required" or assessment != {
            "status": "current",
            "fingerprint": architecture_fingerprint(model),
            "declared_modules": declared,
            "relevant_modules": relevant_records,
        }:
            raise ValueError
    git = inputs["git"]
    if not isinstance(git, list) or any(
        not _exact_keys(record, {"path", "kind"})
        or not _fixture_path(record["path"])
        or record["kind"] not in _GIT_KINDS
        for record in git
    ):
        raise ValueError

    treatment = data["treatment"]
    expected = data["expected"]
    if experiment == "drift_detection":
        if treatment != {
            "name": "architecture_gate",
            "baseline": {"architecture_mode": "off"},
            "adaptive": {"architecture_mode": "required"},
        } or not _exact_keys(
            expected,
            {"label", "blockers", "diagnostics", "expected_modules", "declaration_quality"},
        ):
            raise ValueError
        if expected["label"] not in {
            "drift", "clean", "declaration_quality"
        } or expected["declaration_quality"] not in {
            "complete", "omits_true_owner"
        } or (
            (expected["label"] == "declaration_quality")
            != (expected["declaration_quality"] == "omits_true_owner")
        ):
            raise ValueError
        for key in ("blockers", "diagnostics"):
            records = _identity_records(
                expected[key],
                model_ids=model_ids,
                ownership_ids={rule.id for rule in model.ownership},
            )
            if records is None or (
                key == "diagnostics"
                and any(item["code"] not in _DIAGNOSTIC_CODES for item in records)
            ):
                raise ValueError
        if not _module_id_list(expected["expected_modules"]):
            raise ValueError
    else:
        if treatment != {
            "name": "architecture_projection",
            "baseline": {"architecture_projection": "omitted"},
            "adaptive": {"architecture_projection": "included"},
        } or not _exact_keys(expected, {"projected_modules"}):
            raise ValueError
        projected = expected["projected_modules"]
        canonical_projection = [
            {
                "id": record["id"],
                "responsibility": record["responsibility"],
                "depends_on": record["depends_on"],
            }
            for record in relevant_records
        ]
        if (
            _projected_records(projected, model_ids=model_ids) is None
            or projected != canonical_projection
        ):
            raise ValueError
    return data


def validate_architecture_corpus(corpus: Path) -> list[dict]:
    """Validate independent Architecture experiment fixtures without repository I/O."""
    rows: list[dict] = []
    try:
        if not corpus.is_dir():
            raise ValueError
        for directory in sorted(corpus.iterdir()):
            if not directory.is_dir():
                raise ValueError
            if directory.name not in {"drift", "context"}:
                raise ValueError
            for path in sorted(directory.iterdir()):
                if not path.is_file() or path.suffix != ".yaml":
                    raise ValueError
                rows.append(
                    _validate_architecture_fixture(
                        yaml.safe_load(path.read_text()), directory.name
                    )
                )
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError
        return sorted(rows, key=lambda row: row["id"])
    except (
        ArchitectureError, OSError, UnicodeError, TypeError, yaml.YAMLError, ValueError
    ) as exc:
        raise ValueError("ARCHITECTURE_BENCHMARK_CORPUS_INVALID") from exc


def _architecture_inputs_fingerprint(inputs: object) -> str:
    payload = json.dumps(
        inputs,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_architecture_experiment_fixtures(
    corpus: Path, experiment: str
) -> list[dict]:
    directory_name = {
        "drift_detection": "drift",
        "context_recovery": "context",
    }[experiment]
    rows: list[dict] = []
    try:
        directory = corpus / directory_name
        if not directory.is_dir():
            raise ValueError
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix != ".yaml":
                raise ValueError
            rows.append(
                _validate_architecture_fixture(
                    yaml.safe_load(path.read_text()), directory_name
                )
            )
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError
        return sorted(rows, key=lambda row: row["id"])
    except (
        ArchitectureError, OSError, UnicodeError, TypeError, yaml.YAMLError, ValueError
    ) as exc:
        raise ValueError("ARCHITECTURE_BENCHMARK_CORPUS_INVALID") from exc


def architecture_fixture_fingerprint(fixture: dict) -> str:
    """Fingerprint immutable experiment inputs, excluding treatment and labels."""
    return _architecture_inputs_fingerprint(fixture["inputs"])


def _count_metric(numerator: int, denominator: int, not_applicable: int = 0) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "not_applicable": not_applicable,
        "value": numerator / denominator if denominator else "not_applicable",
    }


def _valid_result_identity(
    item: object, model_ids: set[str], ownership_ids: set[str]
) -> bool:
    if not _exact_keys(item, {"code", "source"}):
        return False
    code = item["code"]
    source = item["source"]
    if not isinstance(code, str) or code not in _IDENTITY_CODES or not isinstance(source, str):
        return False
    if code in _DIAGNOSTIC_CODES or code == "ARCHITECTURE_EVIDENCE_INVALID":
        return source.startswith("path:") and _fixture_path(source.removeprefix("path:"))
    if code == "ARCHITECTURE_REQUIRED":
        return source == "artifact:.harness/architecture.yaml"
    if code == "ARCHITECTURE_SCOPE_INVALID":
        module_id = source.removeprefix("module:")
        return source.startswith("module:") and _valid_module_id(module_id)
    if code == "ARCHITECTURE_OWNERSHIP_EMPTY":
        ownership_id = source.removeprefix("ownership:")
        return source.startswith("ownership:") and ownership_id in ownership_ids
    match = re.fullmatch(r"path:(.+)\|module:([a-z][a-z0-9]*(?:-[a-z0-9]+)*)", source)
    return bool(
        match
        and _fixture_path(match.group(1))
        and match.group(2) in model_ids
    )


def _identity_records(
    value: object, *, model_ids: set[str], ownership_ids: set[str]
) -> list[dict] | None:
    if not isinstance(value, list) or any(
        not _valid_result_identity(item, model_ids, ownership_ids) for item in value
    ):
        return None
    identities = [(item["code"], item["source"]) for item in value]
    return value if len(identities) == len(set(identities)) else None


def _projected_records(
    value: object, *, model_ids: set[str]
) -> list[dict] | None:
    if not isinstance(value, list) or any(
        not _exact_keys(item, {"id", "responsibility", "depends_on"})
        or not _valid_module_id(item["id"])
        or item["id"] not in model_ids
        or not isinstance(item["responsibility"], str)
        or not item["responsibility"]
        or not _string_list(item["depends_on"])
        or any(
            not _valid_module_id(dependency) or dependency not in model_ids
            for dependency in item["depends_on"]
        )
        for item in value
    ):
        return None
    identities = [item["id"] for item in value]
    return value if len(identities) == len(set(identities)) else None


def _valid_rfc3339(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:(?P<z>[Zz])|(?P<sign>[+-])(?P<hour>\d{2}):(?P<minute>\d{2}))",
        value,
    )
    if match is None or (
        match.group("z") is None
        and (int(match.group("hour")) > 23 or int(match.group("minute")) > 59)
    ):
        return False
    normalized = value.replace("t", "T")
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    leap_second = normalized[17:19] == "60"
    if leap_second:
        normalized = normalized[:17] + "59" + normalized[19:]
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    if leap_second:
        try:
            boundary = (parsed + timedelta(seconds=1)).astimezone(timezone.utc)
            previous_date = (boundary.date() - timedelta(days=1)).isoformat()
        except OverflowError:
            return False
        return (
            boundary.hour == boundary.minute == boundary.second == 0
            and previous_date in _LEAP_SECOND_DATES
        )
    return True


def _architecture_artifact(
    path: Path, fixture: dict, arm: str, experiment: str
) -> dict | None:
    try:
        artifact = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not _exact_keys(
        artifact,
        {
            "version", "fixture_id", "experiment", "arm", "treatment",
            "input_fingerprint", "inputs", "runs",
        },
    ):
        return None
    try:
        persisted_input_fingerprint = _architecture_inputs_fingerprint(
            artifact["inputs"]
        )
    except (TypeError, ValueError, UnicodeError):
        return None
    if (
        type(artifact["version"]) is not int
        or artifact["version"] != 1
        or artifact["fixture_id"] != fixture["id"]
        or artifact["experiment"] != experiment
        or artifact["arm"] != arm
        or artifact["treatment"] != fixture["treatment"][arm]
        or artifact["input_fingerprint"] != architecture_fixture_fingerprint(fixture)
        or persisted_input_fingerprint != artifact["input_fingerprint"]
        or artifact["inputs"] != fixture["inputs"]
        or not isinstance(artifact["runs"], list)
        or len(artifact["runs"]) < 3
    ):
        return None
    model_ids = {
        module["id"] for module in fixture["inputs"]["architecture"]["modules"]
    }
    ownership_ids = {
        rule["id"] for rule in fixture["inputs"]["architecture"]["ownership"]
    }
    run_ids: list[str] = []
    session_ids: list[str] = []
    normalized: list[dict] = []
    efficiency_valid = True
    correctness_run_keys = {"run_id", "provenance", "integrity", "observed"}
    efficiency_run_keys = {"success", "usage"}
    for run in artifact["runs"]:
        if not isinstance(run, dict) or (
            not correctness_run_keys <= set(run)
            or not set(run) <= correctness_run_keys | efficiency_run_keys
        ) or (
            not isinstance(run["run_id"], str)
            or not run["run_id"]
            or not _exact_keys(run["provenance"], {"session_id", "started_at"})
            or not isinstance(run["provenance"]["session_id"], str)
            or not run["provenance"]["session_id"]
            or not _valid_rfc3339(run["provenance"]["started_at"])
            or type(run["integrity"]) is not bool
        ):
            return None
        usage = None
        try:
            if "usage" in run:
                usage = normalize_usage(run["usage"])
        except TelemetryError:
            pass
        run_efficiency_valid = bool(
            usage is not None
            and type(run.get("success")) is bool
            and usage["source"] in {"runtime", "provider"}
            and type(usage["total_tokens"]) is int
            and type(usage["tool_calls"]) is int
        )
        efficiency_valid = efficiency_valid and run_efficiency_valid
        observed = run["observed"]
        if experiment == "drift_detection":
            if not _exact_keys(observed, {"blocked", "blockers", "diagnostics"}):
                return None
            blockers = _identity_records(
                observed["blockers"],
                model_ids=model_ids,
                ownership_ids=ownership_ids,
            )
            diagnostics = _identity_records(
                observed["diagnostics"],
                model_ids=model_ids,
                ownership_ids=ownership_ids,
            )
            if type(observed["blocked"]) is not bool or blockers is None or diagnostics is None:
                return None
        elif not _exact_keys(observed, {"projected_modules"}) or _projected_records(
            observed["projected_modules"], model_ids=model_ids
        ) is None:
            return None
        run_ids.append(run["run_id"])
        session_ids.append(run["provenance"]["session_id"])
        normalized.append(
            {
                **run,
                "success": run.get("success") if run_efficiency_valid else None,
                "total_tokens": usage["total_tokens"] if run_efficiency_valid else None,
                "tool_calls": usage["tool_calls"] if run_efficiency_valid else None,
            }
        )
    if (
        len(run_ids) != len(set(run_ids))
        or len(session_ids) != len(set(session_ids))
    ):
        return None
    observed_by_key: dict[str, dict] = {}
    observed_counts: dict[str, int] = {}
    for run in normalized:
        key = json.dumps(
            run["observed"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        observed_by_key[key] = run["observed"]
        observed_counts[key] = observed_counts.get(key, 0) + 1
    highest_count = max(observed_counts.values())
    modes = [key for key, count in observed_counts.items() if count == highest_count]
    if len(modes) != 1:
        return None
    return {
        **artifact,
        "runs": normalized,
        "representative_observed": observed_by_key[modes[0]],
        "efficiency_valid": efficiency_valid,
    }


def _record_identities(records: list[dict]) -> set[tuple[str, str]]:
    return {(item["code"], item["source"]) for item in records}


def _drift_arm(fixtures: list[dict], artifacts: list[dict]) -> dict:
    drift_total = drift_correct = clean_total = clean_blocked = 0
    declaration_not_applicable = 0
    diagnostic_correct = diagnostic_emitted = diagnostic_na = 0
    integrity_failures = 0
    for fixture, artifact in zip(fixtures, artifacts):
        observed = artifact["representative_observed"]
        expected = fixture["expected"]
        integrity_failures += sum(not run["integrity"] for run in artifact["runs"])
        if expected["label"] == "declaration_quality":
            declaration_not_applicable += 1
            continue
        if expected["label"] == "drift":
            drift_total += 1
            emitted_blockers = _record_identities(observed["blockers"])
            expected_blockers = _record_identities(expected["blockers"])
            drift_correct += bool(observed["blocked"] and expected_blockers <= emitted_blockers)
        else:
            clean_total += 1
            clean_blocked += observed["blocked"]
        diagnostic_codes = {
            "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
            "ARCHITECTURE_OWNERSHIP_AMBIGUOUS",
        }
        emitted = {
            identity
            for identity in _record_identities(observed["diagnostics"])
            if identity[0] in diagnostic_codes
        }
        labeled = {
            identity
            for identity in _record_identities(expected["diagnostics"])
            if identity[0] in diagnostic_codes
        }
        if emitted:
            diagnostic_emitted += len(emitted)
            diagnostic_correct += len(emitted & labeled)
        else:
            diagnostic_na += 1
    return {
        "metrics": {
            "drift_recall": _count_metric(
                drift_correct, drift_total, declaration_not_applicable
            ),
            "diagnostic_precision": _count_metric(
                diagnostic_correct, diagnostic_emitted, diagnostic_na
            ),
            "false_positive_rate": _count_metric(
                clean_blocked, clean_total, declaration_not_applicable
            ),
        },
        "integrity_failures": integrity_failures,
        "efficiency": (
            summarize_runs(
                [run for artifact in artifacts for run in artifact["runs"]]
            )
            if all(artifact["efficiency_valid"] for artifact in artifacts)
            else INCONCLUSIVE
        ),
    }


def _projected_identity(item: dict) -> tuple[str, str, tuple[str, ...]]:
    return item["id"], item["responsibility"], tuple(item["depends_on"])


def _context_arm(fixtures: list[dict], artifacts: list[dict]) -> dict:
    numerator = denominator = unexpected = integrity_failures = 0
    not_applicable = 0
    for fixture, artifact in zip(fixtures, artifacts):
        expected = {
            _projected_identity(item) for item in fixture["expected"]["projected_modules"]
        }
        observed = {
            _projected_identity(item)
            for item in artifact["representative_observed"]["projected_modules"]
        }
        numerator += len(expected & observed)
        denominator += len(expected)
        unexpected += len(observed - expected)
        not_applicable += int(not expected)
        integrity_failures += sum(not run["integrity"] for run in artifact["runs"])
    return {
        "metrics": {
            "context_factual_recovery": _count_metric(
                numerator, denominator, not_applicable
            )
        },
        "unexpected_records": unexpected,
        "integrity_failures": integrity_failures,
        "efficiency": (
            summarize_runs(
                [run for artifact in artifacts for run in artifact["runs"]]
            )
            if all(artifact["efficiency_valid"] for artifact in artifacts)
            else INCONCLUSIVE
        ),
    }


def _metric_value(metric: dict, *, default: float) -> float:
    value = metric["value"]
    return default if value == "not_applicable" else float(value)


def _experiment_status(experiment: str, baseline: dict, adaptive: dict) -> str:
    if adaptive["integrity_failures"]:
        return "FAIL"
    if baseline["integrity_failures"]:
        return INCONCLUSIVE
    if experiment == "context_recovery":
        baseline_value = _metric_value(
            baseline["metrics"]["context_factual_recovery"], default=1.0
        )
        adaptive_value = _metric_value(
            adaptive["metrics"]["context_factual_recovery"], default=1.0
        )
        if (
            adaptive_value < baseline_value
            or adaptive["unexpected_records"] > baseline["unexpected_records"]
        ):
            return "FAIL"
        return "CORRECTNESS_IMPROVED" if adaptive_value > baseline_value else "CORRECTNESS_PRESERVED"

    b = baseline["metrics"]
    a = adaptive["metrics"]
    baseline_recall = _metric_value(b["drift_recall"], default=1.0)
    adaptive_recall = _metric_value(a["drift_recall"], default=1.0)
    baseline_precision = b["diagnostic_precision"]["value"]
    adaptive_precision = a["diagnostic_precision"]["value"]
    precision_comparable = (
        baseline_precision != "not_applicable"
        and adaptive_precision != "not_applicable"
    )
    baseline_fpr = _metric_value(b["false_positive_rate"], default=0.0)
    adaptive_fpr = _metric_value(a["false_positive_rate"], default=0.0)
    adaptive_precision_regresses_from_na = (
        baseline_precision == "not_applicable"
        and adaptive_precision != "not_applicable"
        and float(adaptive_precision) < 1.0
    )
    adaptive_precision_becomes_na = (
        baseline_precision != "not_applicable"
        and adaptive_precision == "not_applicable"
    )
    if (
        adaptive_recall < baseline_recall
        or adaptive_precision_regresses_from_na
        or adaptive_precision_becomes_na
        or (
            precision_comparable
            and float(adaptive_precision) < float(baseline_precision)
        )
        or adaptive_fpr > baseline_fpr
    ):
        return "FAIL"
    improved = (
        adaptive_recall > baseline_recall
        or (
            precision_comparable
            and float(adaptive_precision) > float(baseline_precision)
        )
        or adaptive_fpr < baseline_fpr
    )
    return "CORRECTNESS_IMPROVED" if improved else "CORRECTNESS_PRESERVED"


def _architecture_run_count(path: Path) -> int:
    try:
        document = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return 0
    runs = document.get("runs") if isinstance(document, dict) else None
    return len(runs) if isinstance(runs, list) else 0


def _architecture_report_header(
    experiment: str, fixtures: list[dict], baseline: Path, adaptive: Path
) -> dict:
    return {
        "experiment": experiment,
        "treatment": fixtures[0]["treatment"],
        "status": INCONCLUSIVE,
        "confidence": "high",
        "correctness_precedes_efficiency": True,
        "fixtures": [
            {
                "id": row["id"],
                "baseline_runs": _architecture_run_count(
                    baseline / f"{row['id']}.json"
                ),
                "adaptive_runs": _architecture_run_count(
                    adaptive / f"{row['id']}.json"
                ),
            }
            for row in fixtures
        ],
    }


def _declaration_quality(fixtures: list[dict]) -> dict:
    expected_modules = sum(
        len(row["expected"]["expected_modules"]) for row in fixtures
    )
    absent_modules = sum(
        len(
            set(row["expected"]["expected_modules"])
            - set(row["inputs"]["task"]["declared_modules"])
        )
        for row in fixtures
    )
    return {
        "missed_impact_proxy": _count_metric(
            absent_modules,
            expected_modules,
            sum(not row["expected"]["expected_modules"] for row in fixtures),
        )
    }


def _pending_arm(experiment: str, fixtures: list[dict]) -> dict:
    if experiment == "drift_detection":
        metrics = {
            "drift_recall": {
                "numerator": None,
                "denominator": sum(
                    row["expected"]["label"] == "drift" for row in fixtures
                ),
                "not_applicable": sum(
                    row["expected"]["label"] == "declaration_quality"
                    for row in fixtures
                ),
                "value": INCONCLUSIVE,
            },
            "diagnostic_precision": {
                "numerator": None,
                "denominator": None,
                "not_applicable": None,
                "value": INCONCLUSIVE,
            },
            "false_positive_rate": {
                "numerator": None,
                "denominator": sum(
                    row["expected"]["label"] == "clean" for row in fixtures
                ),
                "not_applicable": sum(
                    row["expected"]["label"] == "declaration_quality"
                    for row in fixtures
                ),
                "value": INCONCLUSIVE,
            },
        }
    else:
        metrics = {
            "context_factual_recovery": {
                "numerator": None,
                "denominator": sum(
                    len(row["expected"]["projected_modules"]) for row in fixtures
                ),
                "not_applicable": 0,
                "value": INCONCLUSIVE,
            }
        }
    return {
        "metrics": metrics,
        "integrity_failures": None,
        "efficiency": INCONCLUSIVE,
    }


def compare_architecture_experiment(
    fixtures: Path,
    baseline: Path,
    adaptive: Path,
    *,
    experiment: str,
) -> dict:
    """Compare one Architecture treatment while keeping experiments separate."""
    if experiment not in {"drift_detection", "context_recovery"}:
        raise ValueError("ARCHITECTURE_BENCHMARK_EXPERIMENT_INVALID")
    try:
        selected = _validate_architecture_experiment_fixtures(fixtures, experiment)
    except ValueError:
        return {"experiment": experiment, "status": INCONCLUSIVE, "confidence": "high"}
    if not selected:
        return {"experiment": experiment, "status": INCONCLUSIVE, "confidence": "high"}
    report = _architecture_report_header(experiment, selected, baseline, adaptive)
    baseline_artifacts = [
        _architecture_artifact(baseline / f"{row['id']}.json", row, "baseline", experiment)
        for row in selected
    ]
    adaptive_artifacts = [
        _architecture_artifact(adaptive / f"{row['id']}.json", row, "adaptive", experiment)
        for row in selected
    ]
    if any(item is None for item in baseline_artifacts + adaptive_artifacts):
        report["baseline"] = _pending_arm(experiment, selected)
        report["adaptive"] = _pending_arm(experiment, selected)
        if experiment == "drift_detection":
            report["declaration_quality"] = _declaration_quality(selected)
        return report
    baseline_valid = [item for item in baseline_artifacts if item is not None]
    adaptive_valid = [item for item in adaptive_artifacts if item is not None]
    all_runs = [
        run
        for artifact in baseline_valid + adaptive_valid
        for run in artifact["runs"]
    ]
    run_ids = [run["run_id"] for run in all_runs]
    session_ids = [run["provenance"]["session_id"] for run in all_runs]
    if (
        len(run_ids) != len(set(run_ids))
        or len(session_ids) != len(set(session_ids))
    ):
        report["baseline"] = _pending_arm(experiment, selected)
        report["adaptive"] = _pending_arm(experiment, selected)
        if experiment == "drift_detection":
            report["declaration_quality"] = _declaration_quality(selected)
        return report
    if experiment == "drift_detection":
        baseline_report = _drift_arm(selected, baseline_valid)
        adaptive_report = _drift_arm(selected, adaptive_valid)
        declaration_quality = _declaration_quality(selected)
    else:
        baseline_report = _context_arm(selected, baseline_valid)
        adaptive_report = _context_arm(selected, adaptive_valid)
        declaration_quality = None
    report["status"] = _experiment_status(
        experiment, baseline_report, adaptive_report
    )
    if report["status"] != "FAIL" and (
        baseline_report["efficiency"] == INCONCLUSIVE
        or adaptive_report["efficiency"] == INCONCLUSIVE
    ):
        report["status"] = INCONCLUSIVE
    if report["status"] in {"FAIL", INCONCLUSIVE}:
        baseline_report["efficiency"] = INCONCLUSIVE
        adaptive_report["efficiency"] = INCONCLUSIVE
    report["baseline"] = baseline_report
    report["adaptive"] = adaptive_report
    if declaration_quality is not None:
        report["declaration_quality"] = declaration_quality
    return report


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

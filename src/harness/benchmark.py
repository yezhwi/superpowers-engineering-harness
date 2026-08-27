"""Deterministic local benchmark fixture reporting."""
import json
from pathlib import Path
import yaml


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
                required = {"id", "level", "expected_profile", "scenario", "risk_tags", "required_correctness"}
                if not isinstance(data, dict) or required - set(data) or directory.name != data["level"].lower():
                    raise ValueError
                if data["level"] not in profiles or data["expected_profile"] != profiles[data["level"]]:
                    raise ValueError
                if not isinstance(data["id"], str) or not data["id"].startswith(data["level"].lower() + "-") or not isinstance(data["scenario"], str) or not data["scenario"]:
                    raise ValueError
                if not isinstance(data["risk_tags"], list) or not all(isinstance(tag, str) and tag for tag in data["risk_tags"]):
                    raise ValueError
                if not isinstance(data["required_correctness"], list) or (data["level"] == "Q0" and data["required_correctness"]):
                    raise ValueError
                rows.append(data)
        if len({row["id"] for row in rows}) != len(rows) or {level: sum(row["level"] == level for row in rows) for level in expected} != expected:
            raise ValueError
        return rows
    except (OSError, TypeError, yaml.YAMLError, ValueError) as exc:
        raise ValueError("BENCHMARK_CORPUS_INVALID") from exc


def _artifact(path: Path, fixture_id: str, mode: str):
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("fixture_id") != fixture_id or data.get("mode") != mode:
        return None
    if not isinstance(data.get("correctness"), dict) or not isinstance(data.get("metrics"), dict):
        return None
    return data


def compare_benchmarks(fixtures: Path, baseline: Path, adaptive: Path) -> dict:
    rows = []
    for path in sorted(fixtures.glob("*.yaml")):
        fixture = yaml.safe_load(path.read_text())
        if not isinstance(fixture, dict) or not isinstance(fixture.get("id"), str) or not isinstance(fixture.get("required_correctness"), list):
            raise ValueError(f"BENCHMARK_FIXTURE_INVALID: {path}")
        fid = fixture["id"]
        before = _artifact(baseline / f"{fid}.json", fid, "baseline")
        after = _artifact(adaptive / f"{fid}.json", fid, "adaptive")
        status = "CORRECTNESS_PRESERVED"
        if before is None or after is None or any(before["correctness"].get(key) is None or after["correctness"].get(key) is None for key in fixture["required_correctness"]):
            status = "INCONCLUSIVE"
        elif any(after["correctness"].get(key) is not True for key in fixture["required_correctness"]):
            status = "CORRECTNESS_REGRESSION"
        metrics = {}
        for key in ("token_estimate", "tool_calls", "elapsed_seconds"):
            left = before["metrics"].get(key) if before else None
            right = after["metrics"].get(key) if after else None
            metrics[f"{key}_delta"] = right - left if isinstance(left, (int, float)) and isinstance(right, (int, float)) else None
        rows.append({"id": fid, "level": fixture.get("level"), "required_correctness": fixture["required_correctness"], "status": status, "metrics": metrics, "baseline": before, "adaptive": after})
    statuses = {row["status"] for row in rows}
    overall = "CORRECTNESS_REGRESSION" if "CORRECTNESS_REGRESSION" in statuses else ("INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "CORRECTNESS_PRESERVED")
    return {"overall": overall, "fixtures": rows}


def evaluate_acceptance(report: dict, fixtures: list[dict]) -> dict:
    rows = report.get("fixtures", [])
    result = {}
    q1 = [row for row in rows if row.get("level") == "Q1"]
    for ac, metric in (("AC16", "tool_calls"), ("AC17", "token_estimate"), ("AC18", "elapsed_seconds")):
        if len(q1) != 20:
            result[ac] = {"status": "INCONCLUSIVE"}
            continue
        pairs = [((row.get("baseline") or {}).get("metrics", {}).get(metric), (row.get("adaptive") or {}).get("metrics", {}).get(metric)) for row in q1]
        if not all(isinstance(left, (int, float)) and isinstance(right, (int, float)) for left, right in pairs):
            result[ac] = {"status": "INCONCLUSIVE"}
        else:
            result[ac] = {"status": "PASS" if sum(right for _, right in pairs) / 20 < sum(left for left, _ in pairs) / 20 else "FAIL"}
    expected_rows = len(fixtures) if fixtures else len(rows)
    complete = expected_rows == 50 and len(rows) == expected_rows and all(
        row.get("status") == "CORRECTNESS_PRESERVED"
        and all((row.get("baseline") or {}).get("correctness", {}).get(key) is True
                and (row.get("adaptive") or {}).get("correctness", {}).get(key) is True
                for key in next((item.get("required_correctness", []) for item in fixtures if item.get("id") == row.get("id")), []))
        for row in rows
    )
    result["AC19"] = {"status": "PASS" if complete else "INCONCLUSIVE"}
    q23 = [row for row in rows if row.get("level") in {"Q2", "Q3"}]
    result["AC20"] = {"status": "PASS" if complete and len(q23) == 20 else "INCONCLUSIVE"}
    return result


def run_benchmarks(fixtures: Path, telemetry: Path) -> dict:
    data = json.loads(telemetry.read_text())
    rows = []
    for path in sorted(fixtures.glob("*.yaml")):
        fixture = yaml.safe_load(path.read_text())
        required = {"id", "risk_level", "expected_profile", "expected_gate"}
        if not isinstance(fixture, dict) or required - set(fixture):
            raise ValueError(f"BENCHMARK_FIXTURE_INVALID: {path}")
        if (data.get("workflow_profile") != fixture["expected_profile"]
                or data.get("gate_result") != fixture["expected_gate"]):
            raise ValueError(f"BENCHMARK_EXPECTATION_MISMATCH: {fixture['id']}")
        rows.append(fixture)
    return {"fixtures": rows, "metrics": {"token_estimate": data.get("token_estimate")}}

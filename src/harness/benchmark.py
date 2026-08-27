"""Deterministic local benchmark fixture reporting."""
import json
from pathlib import Path
import yaml


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
        rows.append({"id": fid, "status": status, "metrics": metrics})
    statuses = {row["status"] for row in rows}
    overall = "CORRECTNESS_REGRESSION" if "CORRECTNESS_REGRESSION" in statuses else ("INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "CORRECTNESS_PRESERVED")
    return {"overall": overall, "fixtures": rows}


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

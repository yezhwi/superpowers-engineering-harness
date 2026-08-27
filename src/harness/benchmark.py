"""Deterministic local benchmark fixture reporting."""
import json
from pathlib import Path
import yaml


def run_benchmarks(fixtures: Path, telemetry: Path) -> dict:
    data = json.loads(telemetry.read_text())
    rows = []
    for path in sorted(fixtures.glob("*.yaml")):
        fixture = yaml.safe_load(path.read_text())
        required = {"id", "risk_level", "expected_profile", "expected_gate"}
        if not isinstance(fixture, dict) or required - set(fixture):
            raise ValueError(f"BENCHMARK_FIXTURE_INVALID: {path}")
        rows.append(fixture)
    return {"fixtures": rows, "metrics": {"token_estimate": data.get("token_estimate")}}
